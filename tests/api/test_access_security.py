"""Z6: Sicherheitstests fuer getrennte Zugaenge, gebuendelt.

Angriffe eines Agenten, der nur das Agent-Token hat: Umgehung der human-Pruefung
per channel, unbekannte und neue Routen, Verwechslung oder Kombination von
Tokens - und die Warnung, wenn der MCP-Server doch das Mensch-Token bekommt.
"""

import sys
from pathlib import Path

import pytest

pytest.importorskip("flask")
pytest.importorskip("mcp")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_consultations_api import AGENT_TOKEN, HUMAN_TOKEN, env  # noqa: E402,F401 - Fixture

from conclave.cli.config import ConclaveConfig  # noqa: E402


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def app(tmp_path):
    from conclave.api.server import _build_app
    app, _ = _build_app(ConclaveConfig(db_path=tmp_path / "c.db", api_key=HUMAN_TOKEN, agent_api_key=AGENT_TOKEN))
    app.config["TESTING"] = True
    return app


# ── Umgehung der human-Pruefung (Luecke aus v0.4.0) ───────────────────────

@pytest.mark.parametrize("body_extra, status, error_type", [
    ({}, 403, "HumanOnlyTicket"),
    ({"requested_by": "laszlo"}, 403, "HumanOnlyTicket"),
    ({"origin": "human"}, 403, "HumanOnlyTicket"),
    ({"channel": "human"}, 400, "ChannelNotAllowed"),
    ({"channel": "rest"}, 400, "ChannelNotAllowed"),
    ({"channel": ""}, 400, "ChannelNotAllowed"),
])
def test_agent_cannot_reach_a_human_ticket_by_any_body(env, body_extra, status, error_type):
    resp = env.agent.post("/consultations", json={"task": "api#20", "question": "?", **body_extra})
    assert (resp.status_code, resp.get_json()["type"]) == (status, error_type)
    assert env.repo.list_by_source_ref("kanzo", "api#20") == []
    assert env.kanzo.tasks["api#20"].comments == []


def test_agent_cannot_upgrade_with_a_second_header(env):
    """Authorization gewinnt; ein zusaetzliches X-API-Key mit dem Mensch-Token hebt nicht an."""
    resp = env.agent.post("/consultations", json={"task": "api#20", "question": "?"},
                          headers={"X-API-Key": HUMAN_TOKEN})
    assert resp.status_code == 403 and resp.get_json()["type"] == "HumanOnlyTicket"


# ── Unbekannte und neue Routen ────────────────────────────────────────────

def test_new_route_is_denied_for_agents_by_default(app):
    app.add_url_rule("/geheim", "geheim", lambda: "nur fuer Menschen", methods=["GET", "POST"])
    c = app.test_client()
    for method in ("GET", "POST"):
        resp = c.open("/geheim", method=method, json={}, headers=_bearer(AGENT_TOKEN))
        assert resp.status_code == 403 and resp.get_json()["type"] == "HumanOnly"
    assert c.get("/geheim", headers=_bearer(HUMAN_TOKEN)).status_code == 200


@pytest.mark.parametrize("path", ["/settings", "/logs", "/backups", "/agents/x", "/runs",
                                  "/conversations/x/rules", "/usage/conversations"])
def test_human_only_reads_are_denied(app, path):
    resp = app.test_client().get(path, headers=_bearer(AGENT_TOKEN))
    assert resp.status_code == 403 and resp.get_json()["type"] == "HumanOnly"


def test_path_tricks_do_not_reach_human_routes(app):
    c = app.test_client()
    for path in ("/settings/", "//settings", "/SETTINGS", "/settings?x=1", "/./settings"):
        status = c.put(path, json={}, headers=_bearer(AGENT_TOKEN)).status_code
        assert not 200 <= status < 300, (path, status)            # 403, 404, 405, 308 oder 421 (Host)


# ── Verwechslung und Kombination von Tokens ───────────────────────────────

@pytest.mark.parametrize("token", [HUMAN_TOKEN + AGENT_TOKEN, AGENT_TOKEN + " ", " " + AGENT_TOKEN,
                                   AGENT_TOKEN.upper(), AGENT_TOKEN[:-1], "cvh_" + AGENT_TOKEN[4:]])
def test_altered_tokens_are_rejected(app, token):
    assert app.test_client().get("/auth/whoami", headers=_bearer(token)).status_code == 401


def test_prefix_does_not_decide_the_role(tmp_path):
    """Ein cva_-Wert in CONCLAVE_API_KEY ist ein Mensch-Token, ein cvh_-Wert als Agent-Token ein Agent."""
    from conclave.api.server import _build_app
    app, _ = _build_app(ConclaveConfig(db_path=tmp_path / "c.db", api_key="cva_sieht-aus-wie-agent",
                                       agent_api_key="cvh_sieht-aus-wie-mensch"))
    c = app.test_client()
    assert c.get("/auth/whoami", headers=_bearer("cva_sieht-aus-wie-agent")).get_json() == {"role": "human"}
    assert c.get("/auth/whoami", headers=_bearer("cvh_sieht-aus-wie-mensch")).get_json() == {"role": "agent"}


def test_token_in_query_string_is_not_accepted(app):
    assert app.test_client().get(f"/auth/whoami?token={AGENT_TOKEN}").status_code == 401


# ── MCP-Server mit dem Mensch-Token ───────────────────────────────────────

def test_mcp_server_refuses_the_human_token(monkeypatch, capsys):
    """R2: Mit dem Mensch-Token arbeitet der MCP-Server nicht (frueher nur eine Warnung)."""
    import httpx
    from mcp.server.mcpserver.exceptions import ToolError

    import conclave.mcp_server as server

    seen = {}

    def fake_get(url, headers=None, **kw):
        seen["auth"] = headers.get("Authorization")
        return httpx.Response(200, json={"role": "human"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(server, "_confirmed_token", None)
    monkeypatch.delenv("CONCLAVE_MCP_ALLOW_HUMAN", raising=False)
    monkeypatch.setattr(server.httpx, "get", fake_get)
    monkeypatch.setenv("CONCLAVE_AGENT_KEY", HUMAN_TOKEN)
    with pytest.raises(ToolError, match="Mensch-Token"):
        server._check_role()
    assert HUMAN_TOKEN not in capsys.readouterr().err
    assert seen["auth"] == f"Bearer {HUMAN_TOKEN}"


# ── R4 (conclave#34): frei waehlbare IDs ──────────────────────────────────

@pytest.mark.parametrize("pid", ["../x", "../../../backup?", "a/b", "x?y=1", "x#y", ".", "..", "a b", "x" * 65, "ä"])
def test_participant_ids_are_checked(app, pid):
    c = app.test_client()
    conv = c.post("/conversations", json={}, headers=_bearer(AGENT_TOKEN)).get_json()["conversation_id"]
    for token in (AGENT_TOKEN, HUMAN_TOKEN):
        resp = c.post(f"/conversations/{conv}/participants", json={"participant_id": pid, "name": "P"},
                      headers=_bearer(token))
        assert resp.status_code == 400 and resp.get_json()["type"] == "ValidationError", (pid, token)


def test_valid_participant_id_is_accepted(app):
    c = app.test_client()
    conv = c.post("/conversations", json={}, headers=_bearer(AGENT_TOKEN)).get_json()["conversation_id"]
    resp = c.post(f"/conversations/{conv}/participants", json={"participant_id": "gpt-5.1_x", "name": "P"},
                  headers=_bearer(AGENT_TOKEN))
    assert resp.status_code == 201


@pytest.mark.parametrize("agent_id", ["../x", "a/b", "..", "x?y"])
def test_new_agent_ids_are_checked(app, agent_id):
    resp = app.test_client().post("/agents", json={"id": agent_id, "name": "A", "model": "m"},
                                  headers=_bearer(HUMAN_TOKEN))
    assert resp.status_code == 400 and resp.get_json()["type"] == "ValidationError"
