"""Z1: Mensch- und Agent-Token, Principal in flask.g, GET /auth/whoami."""

import logging
import os
import stat

import pytest
pytest.importorskip("flask")

from unittest.mock import MagicMock

from conclave.api.app import create_app
from conclave.cli.config import ConclaveConfig
from conclave.cli.handler import CLIResult
from conclave.infrastructure.auth import StaticKeyAuthService
from conclave.runtime import api_token

HUMAN = "cvh_mensch-token"
AGENT = "cva_agent-token"


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client():
    handler = MagicMock()
    handler.list_conversations.return_value = CLIResult(success=True, message="ok", data={"conversations": []})
    app = create_app(handler, auth_service=StaticKeyAuthService(HUMAN, AGENT))
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.mark.parametrize("token, role", [(HUMAN, "human"), (AGENT, "agent")])
def test_whoami_returns_role_of_token(client, token, role):
    resp = client.get("/auth/whoami", headers=_bearer(token))
    assert resp.status_code == 200
    assert resp.get_json() == {"role": role}


def test_whoami_accepts_x_api_key(client):
    assert client.get("/auth/whoami", headers={"X-API-Key": AGENT}).get_json() == {"role": "agent"}


@pytest.mark.parametrize("headers", [{}, _bearer("falsch"), _bearer(""), _bearer(HUMAN + AGENT)])
def test_wrong_or_missing_token_is_401(client, headers):
    assert client.get("/auth/whoami", headers=headers).status_code == 401
    assert client.get("/conversations", headers=headers).status_code == 401


def test_agent_token_reaches_routes_in_z1(client):
    # Z1 erkennt nur die Rolle; die Rechte des Agent-Zugangs regelt erst Z2.
    assert client.get("/conversations", headers=_bearer(AGENT)).status_code == 200


def test_whoami_without_auth_service_is_human():
    app = create_app(MagicMock())
    assert app.test_client().get("/auth/whoami").get_json() == {"role": "human"}


# ── Token-Dateien ─────────────────────────────────────────────────────────

def test_new_tokens_carry_prefixes(tmp_path):
    assert api_token.load_or_create_token(tmp_path / "api.token").startswith("cvh_")
    assert api_token.load_or_create_agent_token(tmp_path / "agent.token").startswith("cva_")


def test_agent_token_file_is_created_once_and_reused(tmp_path):
    path = tmp_path / "sub" / "agent.token"
    first = api_token.load_or_create_agent_token(path)
    assert len(first) >= 40
    assert api_token.load_or_create_agent_token(path) == first


@pytest.mark.skipif(os.name == "nt", reason="POSIX-Dateirechte")
def test_agent_token_file_is_private_on_posix(tmp_path):
    path = tmp_path / "agent.token"
    api_token.load_or_create_agent_token(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_read_agent_token_prefers_environment(monkeypatch, tmp_path):
    path = tmp_path / "agent.token"
    monkeypatch.setenv("CONCLAVE_AGENT_TOKEN_FILE", str(path))
    assert api_token.read_agent_token() == ""
    api_token.load_or_create_agent_token(path)
    assert api_token.read_agent_token() == path.read_text(encoding="utf-8").strip()
    monkeypatch.setenv("CONCLAVE_AGENT_KEY", "cva_from-env")
    assert api_token.read_agent_token() == "cva_from-env"


def test_agent_token_path_defaults_to_config_dir(monkeypatch):
    monkeypatch.delenv("CONCLAVE_AGENT_TOKEN_FILE", raising=False)
    from conclave.runtime.paths import get_runtime_paths
    assert api_token.agent_token_path() == get_runtime_paths().config_dir / "agent.token"


# ── Ganzer Server ─────────────────────────────────────────────────────────

def _build(tmp_path, **config):
    from conclave.api.server import _build_app
    return _build_app(ConclaveConfig(db_path=tmp_path / "c.db", **config))


def test_server_creates_agent_token_and_recognises_both(tmp_path):
    app, config = _build(tmp_path, api_key="")
    human = (tmp_path / "api.token").read_text(encoding="utf-8").strip()
    agent = (tmp_path / "agent.token").read_text(encoding="utf-8").strip()
    assert (config.api_key, config.agent_api_key) == (human, agent)
    assert human.startswith("cvh_") and agent.startswith("cva_")
    c = app.test_client()
    assert c.get("/auth/whoami", headers=_bearer(human)).get_json() == {"role": "human"}
    assert c.get("/auth/whoami", headers=_bearer(agent)).get_json() == {"role": "agent"}


def test_legacy_api_token_without_prefix_is_human(tmp_path):
    (tmp_path / "api.token").write_text("altes-token-ohne-praefix\n", encoding="utf-8")
    app, _ = _build(tmp_path, api_key="")
    resp = app.test_client().get("/auth/whoami", headers=_bearer("altes-token-ohne-praefix"))
    assert resp.get_json() == {"role": "human"}


def test_explicit_agent_key_wins_over_token_file(tmp_path):
    app, config = _build(tmp_path, api_key="explicit", agent_api_key="cva_explicit")
    assert config.agent_api_key == "cva_explicit"
    assert not (tmp_path / "agent.token").exists()
    resp = app.test_client().get("/auth/whoami", headers=_bearer("cva_explicit"))
    assert resp.get_json() == {"role": "agent"}


def test_agent_key_equal_to_human_key_gives_no_agent_access(tmp_path):
    app, _ = _build(tmp_path, api_key="gleich", agent_api_key="gleich")
    assert app.test_client().get("/auth/whoami", headers=_bearer("gleich")).get_json() == {"role": "human"}


def test_config_reads_agent_key_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("CONCLAVE_AGENT_KEY", "cva_env")
    assert ConclaveConfig.from_sources(tmp_path / "fehlt.toml").agent_api_key == "cva_env"


def test_tokens_never_appear_in_logs(tmp_path, caplog):
    """Tokens stehen weder im Log-Capture noch in der Log-Datei, auch nicht gekuerzt."""
    caplog.set_level(logging.DEBUG)
    app, config = _build(tmp_path, api_key="")
    c = app.test_client()
    for headers in (_bearer(config.api_key), _bearer(config.agent_api_key), {"X-API-Key": config.agent_api_key},
                    _bearer("cva_falsch-geraten"), {}):
        c.get("/auth/whoami", headers=headers)
        c.get("/conversations", headers=headers)
        c.post("/conversations", json={}, headers=headers)
    text = caplog.text + "".join(p.read_text(encoding="utf-8", errors="replace")
                                 for p in (tmp_path / "logs").rglob("*") if p.is_file())
    assert "Token erzeugt" in text                    # das Log wurde wirklich erfasst
    for token in (config.api_key, config.agent_api_key, "cva_falsch-geraten"):
        secret = token.split("_", 1)[1]
        for part in (token, secret[:8], secret[-8:]):
            assert part not in text, part


def test_token_variables_are_not_seeded_as_agents(monkeypatch, tmp_path, capsys):
    """CONCLAVE_AGENT_KEY/_TOKEN_FILE teilen das Praefix der Agent-Seeds (CONCLAVE_AGENT_<ID>)."""
    monkeypatch.setenv("CONCLAVE_AGENT_KEY", "cva_a:b:c")
    monkeypatch.setenv("CONCLAVE_AGENT_TOKEN_FILE", r"C:\x\agent.token")
    from conclave.api.server import _build_app
    config = ConclaveConfig.from_sources(tmp_path / "fehlt.toml")
    config.db_path = tmp_path / "c.db"
    app, config = _build_app(config)
    c = app.test_client()
    resp = c.get("/agents", headers=_bearer(config.api_key))
    assert resp.status_code == 200
    agents = resp.get_json()
    ids = {a["id"] for a in (agents["agents"] if isinstance(agents, dict) else agents)}
    assert not {"KEY", "TOKEN_FILE"} & ids
    assert "cva_a" not in capsys.readouterr().out
    assert c.get("/auth/whoami", headers=_bearer("cva_a:b:c")).get_json() == {"role": "agent"}
