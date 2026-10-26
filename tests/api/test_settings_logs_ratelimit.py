# tests/api/test_settings_logs_ratelimit.py

"""Settings-Seite: Server-Log lesen, Rate-Limit anzeigen und zur Laufzeit aendern."""

import json
import logging
import tomllib

import pytest
pytest.importorskip("flask")
pytest.importorskip("flask_limiter")

from unittest.mock import MagicMock

from conclave.api.app import create_app
from conclave.cli.config import ConclaveConfig
from conclave.cli.handler import CLIResult
from conclave.infrastructure.log import configure_logging, read_log_tail


@pytest.fixture
def handler():
    h = MagicMock()
    h.list_conversations.return_value = CLIResult(success=True, message="ok", data={"conversations": []})
    return h


def _client(handler, config):
    app = create_app(handler, config=config)
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def file_logging(tmp_path):
    path = tmp_path / "logs" / "conclave-server.log"
    logger = configure_logging("INFO", path)
    yield path
    for h in list(logger.handlers):
        if getattr(h, "_conclave_managed", False):
            logger.removeHandler(h)
            h.close()


# ── Rate-Limit ────────────────────────────────────────────────────────────

def test_settings_show_rate_limit(handler):
    config = ConclaveConfig(rate_limit="50 per minute", rate_limit_source="config")
    rl = _client(handler, config).get("/settings").get_json()["settings"]["rate_limit"]
    assert rl == {"value": "50 per minute", "source": "config", "active": True,
                  "editable": True, "persistent": False}


def test_rate_limit_change_takes_effect_immediately(handler):
    client = _client(handler, ConclaveConfig(rate_limit="100 per minute"))
    assert client.put("/settings", json={"rate_limit": "2 per minute"}).status_code == 200
    statuses = [client.get("/conversations").status_code for _ in range(3)]
    assert statuses[-1] == 429


def test_rate_limit_can_be_switched_off_and_on_at_runtime(handler):
    client = _client(handler, ConclaveConfig(rate_limit="1 per minute"))
    client.get("/conversations")
    assert client.get("/conversations").status_code == 429
    assert client.put("/settings", json={"rate_limit": "off"}).status_code == 200
    assert all(client.get("/conversations").status_code == 200 for _ in range(3))
    settings = client.get("/settings").get_json()["settings"]["rate_limit"]
    assert settings["active"] is False and settings["value"] == "off"


def test_rate_limit_change_is_persisted_to_config_toml(handler, tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text('# meine Config\n[database]\nprovider = "sqlite"\n', encoding="utf-8")
    config = ConclaveConfig.from_sources(config_file)
    client = _client(handler, config)
    resp = client.put("/settings", json={"rate_limit": "300 per minute"})
    assert resp.status_code == 200
    assert resp.get_json()["settings"]["rate_limit"]["persistent"] is True
    data = tomllib.loads(config_file.read_text(encoding="utf-8"))
    assert data["server"]["rate_limit"] == "300 per minute"
    assert data["database"]["provider"] == "sqlite"
    assert "# meine Config" in config_file.read_text(encoding="utf-8")
    assert ConclaveConfig.from_sources(config_file).rate_limit == "300 per minute"


def test_invalid_rate_limit_is_rejected_and_not_applied(handler, tmp_path):
    client = _client(handler, ConclaveConfig(rate_limit="100 per minute"))
    for value in ("viele", ""):
        resp = client.put("/settings", json={"rate_limit": value})
        assert resp.status_code == 400
        assert resp.get_json()["type"] == "InvalidRateLimit"
    assert client.get("/settings").get_json()["settings"]["rate_limit"]["value"] == "100 per minute"


def test_rate_limit_from_environment_is_locked(handler, monkeypatch, tmp_path):
    monkeypatch.setenv("CONCLAVE_RATE_LIMIT", "80 per minute")
    config = ConclaveConfig.from_sources(tmp_path / "config.toml")
    client = _client(handler, config)
    assert client.get("/settings").get_json()["settings"]["rate_limit"]["editable"] is False
    resp = client.put("/settings", json={"rate_limit": "5 per minute"})
    assert resp.status_code == 409
    assert resp.get_json()["type"] == "RateLimitLocked"
    assert not (tmp_path / "config.toml").exists()


def test_rate_limit_source_detection(monkeypatch, tmp_path):
    monkeypatch.delenv("CONCLAVE_RATE_LIMIT", raising=False)
    assert ConclaveConfig.from_sources(tmp_path / "none.toml").rate_limit_source == "default"
    (tmp_path / "c.toml").write_text('[server]\nrate_limit = "10/minute"\n', encoding="utf-8")
    assert ConclaveConfig.from_sources(tmp_path / "c.toml").rate_limit_source == "config"


# ── Logs ──────────────────────────────────────────────────────────────────

def test_logs_unavailable_without_file_logging(handler):
    body = _client(handler, ConclaveConfig()).get("/logs").get_json()
    assert body["available"] is False
    assert body["entries"] == []


def test_logs_return_recent_entries_with_level_filter(handler, file_logging):
    log = logging.getLogger("conclave.test")
    log.info("hallo info")
    log.warning("achtung")
    log.error("kaputt")
    client = _client(handler, ConclaveConfig())

    body = client.get("/logs").get_json()
    assert body["available"] is True
    assert body["log_file"] == str(file_logging)
    messages = [e["message"] for e in body["entries"]]
    assert messages[-3:] == ["hallo info", "achtung", "kaputt"]

    warnings = [e["message"] for e in client.get("/logs?level=WARNING").get_json()["entries"]]
    assert "hallo info" not in warnings and "achtung" in warnings and "kaputt" in warnings


def test_logs_validate_parameters(handler, file_logging):
    client = _client(handler, ConclaveConfig())
    assert client.get("/logs?limit=abc").status_code == 400
    assert client.get("/logs?level=LOUD").status_code == 400
    assert len(client.get("/logs?limit=1").get_json()["entries"]) <= 1


def test_settings_report_log_file(handler, file_logging):
    settings = _client(handler, ConclaveConfig()).get("/settings").get_json()["settings"]
    assert settings["log_file"] == str(file_logging)


def test_logs_require_token(handler, file_logging):
    from conclave.infrastructure.auth import StaticKeyAuthService
    app = create_app(handler, auth_service=StaticKeyAuthService("t"), config=ConclaveConfig())
    assert app.test_client().get("/logs").status_code == 401


def test_read_log_tail_handles_large_and_non_json_lines(tmp_path):
    path = tmp_path / "big.log"
    lines = [json.dumps({"timestamp": f"t{i}", "level": "INFO", "message": f"m{i}"}) for i in range(5000)]
    lines.insert(4990, "kein json")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    entries = read_log_tail(path, limit=20, max_bytes=4096)
    assert entries[-1]["message"] == "m4999"
    assert len(entries) == 20
    assert any(e["level"] == "RAW" and e["message"] == "kein json" for e in entries)
    assert read_log_tail(path, limit=5, min_level="ERROR") == [
        e for e in entries if e["level"] == "RAW"][-5:]


def test_successful_reads_are_not_logged_at_info(handler, file_logging):
    client = _client(handler, ConclaveConfig())
    client.get("/conversations")
    client.get("/static/js/utils.js")
    client.post("/conversations", json={})
    client.get("/does-not-exist")
    messages = [e["message"] for e in read_log_tail(file_logging, limit=50)]
    assert not any(m.startswith("GET /conversations") for m in messages)
    assert not any(m.startswith("GET /static/") for m in messages)
    assert any(m.startswith("POST /conversations") for m in messages)
    assert any(m.startswith("GET /does-not-exist") for m in messages)


def test_config_file_location_can_be_overridden(monkeypatch, tmp_path):
    from conclave.cli.config import default_config_path
    target = tmp_path / "eigene.toml"
    target.write_text('[server]\nrate_limit = "7/minute"\n', encoding="utf-8")
    monkeypatch.setenv("CONCLAVE_CONFIG_FILE", str(target))
    monkeypatch.delenv("CONCLAVE_RATE_LIMIT", raising=False)
    assert default_config_path() == target
    config = ConclaveConfig.from_sources()
    assert config.config_path == target
    assert config.rate_limit == "7/minute"
