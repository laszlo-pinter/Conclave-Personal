"""Z4: Herkunft von Nachrichten ueber die API - gesetzt aus dem Token, sichtbar in GET und Export."""

import pytest
pytest.importorskip("flask")

from conclave.cli.config import ConclaveConfig

HUMAN = "cvh_mensch-token"
AGENT = "cva_agent-token"


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def app_and_service(tmp_path):
    from conclave.api.server import _build_app
    app, _ = _build_app(ConclaveConfig(db_path=tmp_path / "c.db", api_key=HUMAN, agent_api_key=AGENT))
    app.config["TESTING"] = True
    return app


def _new_conversation(c):
    return c.post("/conversations", json={}, headers=_bearer(HUMAN)).get_json()["conversation_id"]


def test_origin_follows_the_token(app_and_service):
    c = app_and_service.test_client()
    conv = _new_conversation(c)
    agent = c.post(f"/conversations/{conv}/messages", json={"content": "von cc"}, headers=_bearer(AGENT))
    human = c.post(f"/conversations/{conv}/messages", json={"content": "von Laszlo"}, headers=_bearer(HUMAN))
    assert (agent.status_code, agent.get_json()["origin"]) == (201, "agent")
    assert (human.status_code, human.get_json()["origin"]) == (201, "human")

    messages = c.get(f"/conversations/{conv}", headers=_bearer(AGENT)).get_json()["messages"]
    assert [(m["content"], m["author_type"], m["origin"]) for m in messages] == [
        ("von cc", "user", "agent"), ("von Laszlo", "user", "human")]


def test_body_cannot_choose_the_origin(app_and_service):
    c = app_and_service.test_client()
    conv = _new_conversation(c)
    resp = c.post(f"/conversations/{conv}/messages", json={"content": "x", "origin": "human"},
                  headers=_bearer(AGENT))
    assert resp.get_json()["origin"] == "agent"


def test_export_shows_origin_and_old_messages_stay_null(app_and_service, tmp_path):
    c = app_and_service.test_client()
    conv = _new_conversation(c)
    c.post(f"/conversations/{conv}/messages", json={"content": "von cc"}, headers=_bearer(AGENT))

    # Nachricht ohne Zugang (CLI, alte Daten): unbekannt, nicht "human"
    from conclave.cli.bootstrap import _load_crypto
    from conclave.domain.message import Message
    from conclave.infrastructure.sqlite.connection import ThreadLocalConnection
    from conclave.infrastructure.sqlite.message_repository import SQLiteMessageRepository
    conn = ThreadLocalConnection(tmp_path / "c.db")
    SQLiteMessageRepository(conn, crypto=_load_crypto(), autocommit=True).save(
        Message.create_user_message(conversation_id=conv, content="alt", sequence=0))

    exported = c.get(f"/conversations/{conv}/export", headers=_bearer(HUMAN)).get_json()
    origins = {m["content"]: m["origin"] for m in exported["messages"]}
    assert origins == {"von cc": "agent", "alt": None}
    shown = c.get(f"/conversations/{conv}", headers=_bearer(HUMAN)).get_json()["messages"]
    assert {m["content"]: m["origin"] for m in shown} == origins


def test_mcp_get_messages_passes_origin_through(app_and_service, monkeypatch):
    import conclave.mcp_server as server

    c = app_and_service.test_client()

    def fake_request(method, path, *, timeout, **kwargs):
        resp = c.open(path, method=method, json=kwargs.get("json"), headers=_bearer(AGENT))
        assert resp.status_code < 400, resp.get_json()
        return resp.get_json()

    monkeypatch.setattr(server, "_request", fake_request)
    conv = server.conclave_create_conversation("Z4")["conversation_id"]
    server.conclave_send_message(conv, "ueber MCP")
    assert [(m["content"], m["origin"]) for m in server.conclave_get_messages(conv)] == [("ueber MCP", "agent")]
