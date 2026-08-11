# tests/api/test_error_handling.py

import json

import pytest
pytest.importorskip("flask")

from unittest.mock import MagicMock

from conclave.api.app import create_app
from conclave.cli.handler import CLIResult
from conclave.domain.errors import (
    AdapterNotFound,
    AgentAlreadyExists,
    AgentNotFound,
    ConversationNotFound,
    EmptyConversation,
    FloorNotGranted,
    NoFloorGranted,
    ParticipantAlreadyRegistered,
    ParticipantNotRegistered,
)


@pytest.fixture
def handler():
    return MagicMock()


@pytest.fixture
def client(handler):
    app = create_app(handler)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestErrorFormat:
    """Alle Error-Responses müssen einheitliches Format haben."""

    def test_error_response_has_error_and_type(self, handler, client):
        handler.show_conversation.side_effect = ConversationNotFound("conv-1")
        resp = client.get("/conversations/conv-1")
        body = json.loads(resp.data)
        assert "error" in body
        assert "type" in body

    def test_error_message_is_string(self, handler, client):
        handler.show_conversation.side_effect = ConversationNotFound("conv-1")
        resp = client.get("/conversations/conv-1")
        body = json.loads(resp.data)
        assert isinstance(body["error"], str)
        assert isinstance(body["type"], str)


class TestConversationNotFound:
    def test_returns_404(self, handler, client):
        handler.show_conversation.side_effect = ConversationNotFound("conv-1")
        resp = client.get("/conversations/conv-1")
        assert resp.status_code == 404

    def test_type_field(self, handler, client):
        handler.show_conversation.side_effect = ConversationNotFound("conv-1")
        body = json.loads(client.get("/conversations/conv-1").data)
        assert body["type"] == "ConversationNotFound"

    def test_delete_conversation_not_found(self, handler, client):
        handler.delete_conversation.side_effect = ConversationNotFound("conv-1")
        resp = client.delete("/conversations/conv-1")
        assert resp.status_code == 404


class TestParticipantNotRegistered:
    def test_returns_404(self, handler, client):
        handler.invoke_participant.side_effect = ParticipantNotRegistered("p1", "conv-1")
        resp = client.post("/conversations/conv-1/participants/p1/invoke")
        assert resp.status_code == 404
        body = json.loads(resp.data)
        assert body["type"] == "ParticipantNotRegistered"


class TestParticipantAlreadyRegistered:
    def test_returns_409(self, handler, client):
        handler.add_participant.side_effect = ParticipantAlreadyRegistered("p1", "conv-1")
        resp = client.post(
            "/conversations/conv-1/participants",
            json={"participant_id": "p1", "name": "Claude", "type": "model"},
        )
        assert resp.status_code == 409
        body = json.loads(resp.data)
        assert body["type"] == "ParticipantAlreadyRegistered"


class TestAdapterNotFound:
    def test_returns_502(self, handler, client):
        handler.invoke_participant.side_effect = AdapterNotFound("p1")
        resp = client.post("/conversations/conv-1/participants/p1/invoke")
        assert resp.status_code == 502
        body = json.loads(resp.data)
        assert body["type"] == "AdapterNotFound"


class TestAgentNotFound:
    def test_returns_404(self, handler, client):
        handler.get_agent.side_effect = AgentNotFound("a1")
        resp = client.get("/agents/a1")
        assert resp.status_code == 404
        body = json.loads(resp.data)
        assert body["type"] == "AgentNotFound"


class TestAgentAlreadyExists:
    def test_returns_409(self, handler, client):
        handler.create_agent.side_effect = AgentAlreadyExists("a1")
        resp = client.post("/agents", json={
            "id": "a1", "name": "Test", "provider": "anthropic", "model": "m",
        })
        assert resp.status_code == 409
        body = json.loads(resp.data)
        assert body["type"] == "AgentAlreadyExists"


class TestNoFloorGranted:
    def test_returns_409(self, handler, client):
        handler.invoke_with_floor.side_effect = NoFloorGranted("conv-1")
        resp = client.post("/conversations/conv-1/floor/invoke")
        assert resp.status_code == 409
        body = json.loads(resp.data)
        assert body["type"] == "NoFloorGranted"


class TestEmptyConversation:
    def test_returns_400(self, handler, client):
        handler.invoke_participant.side_effect = EmptyConversation("conv-1")
        resp = client.post("/conversations/conv-1/participants/p1/invoke")
        assert resp.status_code == 400
        body = json.loads(resp.data)
        assert body["type"] == "EmptyConversation"

    def test_cli_result_returns_400(self, handler, client):
        handler.invoke_participant.return_value = CLIResult(
            success=False,
            message="Bitte zuerst eine Nachricht schreiben.",
            data={"type": "EmptyConversation", "status": 400},
        )
        resp = client.post("/conversations/conv-1/participants/p1/invoke")
        assert resp.status_code == 400
        body = json.loads(resp.data)
        assert body["type"] == "EmptyConversation"


class TestFloorNotGranted:
    def test_returns_409(self, handler, client):
        handler.grant_floor.side_effect = FloorNotGranted("p1", None)
        resp = client.post(
            "/conversations/conv-1/floor/grant",
            json={"participant_id": "p1"},
        )
        assert resp.status_code == 409
        body = json.loads(resp.data)
        assert body["type"] == "FloorNotGranted"


class TestValueError:
    def test_returns_400(self, handler, client):
        handler.add_message.side_effect = ValueError("Ungültiger Wert")
        resp = client.post(
            "/conversations/conv-1/messages",
            json={"content": "test"},
        )
        assert resp.status_code == 400
        body = json.loads(resp.data)
        assert body["type"] == "ValueError"


class TestUnexpectedException:
    def test_returns_500(self, handler, client):
        handler.list_conversations.side_effect = RuntimeError("Unexpected DB crash")
        resp = client.get("/conversations")
        assert resp.status_code == 500

    def test_no_stacktrace_in_body(self, handler, client):
        handler.list_conversations.side_effect = RuntimeError("Unexpected DB crash")
        body = json.loads(client.get("/conversations").data)
        assert "stacktrace" not in body
        assert "Traceback" not in body.get("error", "")

    def test_generic_error_message(self, handler, client):
        handler.list_conversations.side_effect = RuntimeError("secret internal detail")
        body = json.loads(client.get("/conversations").data)
        assert body["type"] == "InternalError"
        assert "secret internal detail" not in body["error"]
