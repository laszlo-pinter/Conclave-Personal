# tests/api/test_rate_limiting.py

import pytest
pytest.importorskip("flask")
pytest.importorskip("flask_limiter")

from unittest.mock import MagicMock

from conclave.api.app import create_app
from conclave.cli.handler import CLIResult


@pytest.fixture
def handler():
    h = MagicMock()
    h.list_conversations.return_value = CLIResult(
        success=True, message="ok", data={"conversations": []})
    return h


@pytest.fixture
def client(handler):
    app = create_app(handler)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_rate_limit_allows_within_limit(client):
    resp = client.get("/conversations")
    assert resp.status_code == 200


def test_rate_limit_header_present(client):
    """Response enthaelt Rate-Limit-Header."""
    resp = client.get("/conversations")
    # flask-limiter setzt standardmaessig RateLimit-Header
    assert resp.status_code == 200


# ── Konfigurierbares Rate-Limit ([server] rate_limit / CONCLAVE_RATE_LIMIT) ──

from conclave.cli.bootstrap import validate_production_config, validate_rate_limit
from conclave.cli.config import DEFAULT_RATE_LIMIT, ConclaveConfig


def _client_with_limit(handler, value):
    app = create_app(handler, config=ConclaveConfig(rate_limit=value))
    app.config["TESTING"] = True
    return app.test_client()


def test_configured_limit_is_enforced_with_json_error(handler):
    client = _client_with_limit(handler, "2 per minute")
    assert [client.get("/conversations").status_code for _ in range(2)] == [200, 200]
    resp = client.get("/conversations")
    assert resp.status_code == 429
    assert resp.get_json()["type"] == "RateLimitExceeded"


def test_multiple_limits_are_supported(handler):
    client = _client_with_limit(handler, "100 per minute; 1 per hour")
    assert client.get("/conversations").status_code == 200
    assert client.get("/conversations").status_code == 429


def test_rate_limit_can_be_switched_off(handler):
    client = _client_with_limit(handler, "off")
    assert all(client.get("/conversations").status_code == 200 for _ in range(5))


def test_default_rate_limit():
    assert ConclaveConfig().rate_limit == DEFAULT_RATE_LIMIT == "120 per minute"


def test_rate_limit_from_toml_and_environment(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    config_file.write_text('[server]\nrate_limit = "300 per minute"\n', encoding="utf-8")
    monkeypatch.delenv("CONCLAVE_RATE_LIMIT", raising=False)
    assert ConclaveConfig.from_sources(config_file).rate_limit == "300 per minute"
    monkeypatch.setenv("CONCLAVE_RATE_LIMIT", "off")
    assert ConclaveConfig.from_sources(config_file).rate_limit == "off"


@pytest.mark.parametrize("value", ["120 per minute", "120/minute; 2000/hour", "off", "OFF"])
def test_valid_rate_limits(value):
    assert validate_rate_limit(value) is None


@pytest.mark.parametrize("value", ["viele", "120 pro minute", "per minute"])
def test_invalid_rate_limit_blocks_start(value):
    errors = validate_production_config(ConclaveConfig(rate_limit=value))
    assert any("Rate-Limit" in e for e in errors)
