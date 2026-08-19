# tests/api/test_api.py

import json
import pytest
pytest.importorskip("flask")

from unittest.mock import MagicMock, patch

from conclave.api.app import create_app
from conclave.cli.handler import CLIResult


@pytest.fixture
def handler():
    h = MagicMock()
    h.new_conversation.return_value = CLIResult(
        success=True,
        message="Erstellt",
        data={"conversation_id": "conv-1"},
    )
    h.show_conversation.return_value = CLIResult(
        success=True,
        message="ok",
        data={
            "id": "conv-1",
            "status": "active",
            "message_count": 1,
            "participant_count": 1,
            "messages": [{"sequence": 1, "author_type": "user", "author_id": None, "content": "Hallo"}],
            "participants": [{"id": "p1", "name": "Claude", "type": "model"}],
        },
    )
    h.add_participant.return_value = CLIResult(
        success=True,
        message="Registriert",
        data={"participant_id": "p1"},
    )
    h.add_message.return_value = CLIResult(
        success=True,
        message="Hinzugefügt",
        data={"sequence": 1, "content": "Hallo"},
    )
    h.invoke_participant.return_value = CLIResult(
        success=True,
        message="Antwort",
        data={"participant_id": "p1", "content": "Modellantwort", "sequence": 2},
    )
    return h


@pytest.fixture
def client(handler):
    app = create_app(handler)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ── POST /conversations ────────────────────────────────────────────────────

def test_post_conversations_returns_201(client):
    res = client.post("/conversations")
    assert res.status_code == 201


def test_post_conversations_returns_conversation_id(client):
    res = client.post("/conversations")
    body = json.loads(res.data)
    assert body["conversation_id"] == "conv-1"


# ── GET /conversations/<id> ────────────────────────────────────────────────

def test_get_conversation_returns_200(client):
    res = client.get("/conversations/conv-1")
    assert res.status_code == 200


def test_get_conversation_returns_full_data(client, handler):
    res = client.get("/conversations/conv-1")
    body = json.loads(res.data)
    assert body["id"] == "conv-1"
    assert body["status"] == "active"
    assert body["message_count"] == 1
    assert len(body["messages"]) == 1
    handler.show_conversation.assert_called_once_with("conv-1")


def test_get_conversation_not_found_returns_404(client, handler):
    handler.show_conversation.return_value = CLIResult(
        success=False,
        message="Nicht gefunden.",
    )
    res = client.get("/conversations/unbekannt")
    assert res.status_code == 404


# ── POST /conversations/<id>/participants ──────────────────────────────────

def test_post_participants_returns_201(client):
    res = client.post(
        "/conversations/conv-1/participants",
        json={"participant_id": "p1", "name": "Claude", "type": "model"},
    )
    assert res.status_code == 201


def test_post_participants_passes_correct_args(client, handler):
    client.post(
        "/conversations/conv-1/participants",
        json={"participant_id": "p1", "name": "Claude", "type": "model"},
    )
    call_kwargs = handler.add_participant.call_args.kwargs
    assert call_kwargs["conversation_id"] == "conv-1"
    assert call_kwargs["participant_id"] == "p1"
    assert call_kwargs["name"] == "Claude"


def test_post_participants_missing_body_returns_400(client):
    res = client.post("/conversations/conv-1/participants", json={})
    assert res.status_code == 400


def test_delete_participant_returns_204(client, handler):
    handler.delete_participant.return_value = CLIResult(success=True, message="ok", data={})

    res = client.delete("/conversations/conv-1/participants/p1")

    assert res.status_code == 204


# ── POST /conversations/<id>/messages ─────────────────────────────────────

def test_post_messages_returns_201(client):
    res = client.post(
        "/conversations/conv-1/messages",
        json={"content": "Hallo Welt"},
    )
    assert res.status_code == 201


def test_post_messages_missing_content_returns_400(client):
    res = client.post("/conversations/conv-1/messages", json={})
    assert res.status_code == 400


def test_post_messages_passes_content(client, handler):
    client.post("/conversations/conv-1/messages", json={"content": "Hallo"})
    handler.add_message.assert_called_once_with("conv-1", "Hallo")


# ── POST /conversations/<id>/participants/<pid>/invoke ─────────────────────

def test_invoke_returns_200(client):
    res = client.post("/conversations/conv-1/participants/p1/invoke")
    assert res.status_code == 200


def test_invoke_returns_model_content(client):
    res = client.post("/conversations/conv-1/participants/p1/invoke")
    body = json.loads(res.data)
    assert body["content"] == "Modellantwort"
    assert body["participant_id"] == "p1"


def test_invoke_failure_returns_502(client, handler):
    handler.invoke_participant.return_value = CLIResult(
        success=False,
        message="Kein Adapter.",
    )
    res = client.post("/conversations/conv-1/participants/p1/invoke")
    assert res.status_code == 502


# ── POST /conversations/<id>/orchestrate ──────────────────────────────────

def test_orchestrate_returns_200(client, handler):
    handler.orchestrate.return_value = CLIResult(
        success=True,
        message="2 Antwort(en) erhalten.",
        data={"responses": [
            {"participant_id": "p1", "content": "Antwort A", "sequence": 2},
            {"participant_id": "p2", "content": "Antwort B", "sequence": 3},
        ]},
    )
    res = client.post(
        "/conversations/conv-1/orchestrate",
        json={"sequence": ["p1", "p2"]},
    )
    assert res.status_code == 200


def test_orchestrate_missing_sequence_returns_400(client):
    res = client.post("/conversations/conv-1/orchestrate", json={})
    assert res.status_code == 400


def test_orchestrate_empty_participant_returns_400(client):
    res = client.post("/conversations/conv-1/orchestrate", json={"sequence": ["p1", " "]})
    assert res.status_code == 400


def test_orchestrate_passes_sequence_to_handler(client, handler):
    handler.orchestrate.return_value = CLIResult(
        success=True, message="ok", data={"responses": []}
    )
    client.post(
        "/conversations/conv-1/orchestrate",
        json={"sequence": ["p1", "p2", "p1"]},
    )
    handler.orchestrate.assert_called_once_with("conv-1", ["p1", "p2", "p1"])


# ── GET /conversations/<id>/participants/<pid>/stream ─────────────────────

def test_stream_endpoint_returns_200(client, handler):
    def fake_stream():
        yield "data: Hallo\n\n"
        yield "data: Welt\n\n"
        yield "data: [DONE]\n\n"

    with patch("conclave.api.app.stream_with_context", return_value=fake_stream()):
        handler.stream_participant = MagicMock(return_value=iter(["Hallo", "Welt"]))
        res = client.get("/conversations/conv-1/participants/p1/stream")
    assert res.status_code == 200


def test_stream_endpoint_content_type_is_event_stream(client, handler):
    handler.stream_participant = MagicMock(return_value=iter(["Hallo"]))
    res = client.get("/conversations/conv-1/participants/p1/stream")
    assert "text/event-stream" in res.content_type


def test_stream_endpoint_wraps_tokens_as_sse(client, handler):
    handler.stream_participant = MagicMock(return_value=iter(["Hel", "lo"]))
    res = client.get("/conversations/conv-1/participants/p1/stream")
    body = res.data.decode()
    assert "data: Hel\n\n" in body
    assert "data: lo\n\n" in body
    assert "data: [DONE]\n\n" in body


# ── GET /conversations ─────────────────────────────────────────────────────

def test_get_conversations_returns_200(client, handler):
    handler.list_conversations.return_value = CLIResult(
        success=True,
        message="2 Conversations gefunden.",
        data={"conversations": [
            {"id": "conv-1", "status": "active", "created_at": "2026-01-01T00:00:00+00:00"},
            {"id": "conv-2", "status": "active", "created_at": "2026-01-02T00:00:00+00:00"},
        ]},
    )
    res = client.get("/conversations")
    assert res.status_code == 200


def test_get_conversations_returns_list(client, handler):
    handler.list_conversations.return_value = CLIResult(
        success=True,
        message="ok",
        data={"conversations": [
            {"id": "conv-1", "status": "active", "created_at": "2026-01-01T00:00:00+00:00"},
        ]},
    )
    body = json.loads(client.get("/conversations").data)
    assert len(body["conversations"]) == 1
    assert body["conversations"][0]["id"] == "conv-1"


# ── DELETE /conversations/<id> ────────────────────────────────────────────

def test_delete_conversation_returns_204(client, handler):
    handler.delete_conversation.return_value = CLIResult(
        success=True,
        message="Gelöscht.",
        data={"conversation_id": "conv-1"},
    )
    res = client.delete("/conversations/conv-1")
    assert res.status_code == 204


def test_delete_conversation_not_found_returns_404(client, handler):
    handler.delete_conversation.return_value = CLIResult(
        success=False,
        message="Nicht gefunden.",
    )
    res = client.delete("/conversations/unbekannt")
    assert res.status_code == 404


# ── CLI: list + delete ─────────────────────────────────────────────────────


# ── Floor & Topic ─────────────────────────────────────────────────────────

def test_post_topic_returns_200(client, handler):
    handler.set_topic.return_value = CLIResult(success=True, message="Thema gesetzt.", data={"topic": "KI"})
    res = client.post("/conversations/conv-1/topic", json={"topic": "KI"})
    assert res.status_code == 200


def test_post_topic_missing_body_returns_400(client):
    res = client.post("/conversations/conv-1/topic", json={})
    assert res.status_code == 400


def test_post_grant_floor_returns_200(client, handler):
    handler.grant_floor.return_value = CLIResult(success=True, message="Rederecht erteilt.", data={"floor": "p1"})
    res = client.post("/conversations/conv-1/floor/grant", json={"participant_id": "p1"})
    assert res.status_code == 200


def test_post_revoke_floor_returns_200(client, handler):
    handler.revoke_floor.return_value = CLIResult(success=True, message="Rederecht entzogen.", data={})
    res = client.post("/conversations/conv-1/floor/revoke")
    assert res.status_code == 200


def test_post_invoke_with_floor_returns_200(client, handler):
    handler.invoke_with_floor.return_value = CLIResult(
        success=True, message="Antwort erhalten.",
        data={"participant_id": "p1", "content": "Hallo", "sequence": 2}
    )
    res = client.post("/conversations/conv-1/floor/invoke")
    assert res.status_code == 200


def test_post_invoke_with_floor_no_floor_returns_409(client, handler):
    handler.invoke_with_floor.return_value = CLIResult(success=False, message="Kein Rederecht.")
    res = client.post("/conversations/conv-1/floor/invoke")
    assert res.status_code == 409
