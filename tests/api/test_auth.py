# tests/api/test_auth.py

import json

import pytest
pytest.importorskip("flask")

from unittest.mock import MagicMock

from conclave.api.app import create_app
from conclave.cli.handler import CLIResult
from conclave.infrastructure.auth import StaticKeyAuthService


@pytest.fixture
def handler():
    h = MagicMock()
    h.list_conversations.return_value = CLIResult(
        success=True, message="ok", data={"conversations": []},
    )
    h.new_conversation.return_value = CLIResult(
        success=True, message="ok", data={"conversation_id": "c1"},
    )
    return h


@pytest.fixture
def auth_service():
    return StaticKeyAuthService(api_key="test-secret-key")


@pytest.fixture
def client(handler, auth_service):
    app = create_app(handler, auth_service=auth_service)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def open_client(handler):
    """Client ohne Auth (Rueckwaertskompatibilitaet)."""
    app = create_app(handler)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestAuthRequired:
    def test_request_without_token_returns_401(self, client):
        resp = client.get("/conversations")
        assert resp.status_code == 401

    def test_request_with_invalid_token_returns_401(self, client):
        resp = client.get("/conversations", headers={"Authorization": "Bearer wrong"})
        assert resp.status_code == 401

    def test_request_with_valid_bearer_returns_200(self, client):
        resp = client.get("/conversations",
                          headers={"Authorization": "Bearer test-secret-key"})
        assert resp.status_code == 200

    def test_request_with_x_api_key_returns_200(self, client):
        resp = client.get("/conversations",
                          headers={"X-API-Key": "test-secret-key"})
        assert resp.status_code == 200

    def test_post_with_valid_token_works(self, client):
        resp = client.post("/conversations",
                           headers={"Authorization": "Bearer test-secret-key"})
        assert resp.status_code == 201


class TestAuthErrorFormat:
    def test_401_has_error_and_type(self, client):
        resp = client.get("/conversations")
        body = json.loads(resp.data)
        assert "error" in body
        assert body["type"] == "AuthenticationError"

    def test_401_message_is_generic(self, client):
        resp = client.get("/conversations")
        body = json.loads(resp.data)
        assert "token" not in body["error"].lower() or "invalid" in body["error"].lower()


class TestNoAuthFallback:
    def test_no_auth_service_means_open_access(self, open_client):
        """Ohne AuthService sind alle Endpoints offen (Rueckwaertskompatibilitaet)."""
        resp = open_client.get("/conversations")
        assert resp.status_code == 200
