# tests/api/test_cors_allowlist.py
#
# Rote Tests: Access-Control-Allow-Origin darf keine beliebige Origin spiegeln.

import pytest
pytest.importorskip("flask")

import os
from unittest.mock import MagicMock
from conclave.api.app import create_app
from conclave.cli.handler import CLIResult


@pytest.fixture
def handler():
    h = MagicMock()
    h.list_conversations.return_value = CLIResult(success=True, message="ok", data={"conversations": []})
    return h


@pytest.fixture
def client_default(handler, monkeypatch):
    """Client ohne CONCLAVE_ALLOWED_ORIGINS → nur localhost."""
    monkeypatch.delenv("CONCLAVE_ALLOWED_ORIGINS", raising=False)
    app = create_app(handler)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def client_with_origin(handler, monkeypatch):
    """Client mit explizit konfigurierter Origin."""
    monkeypatch.setenv("CONCLAVE_ALLOWED_ORIGINS", "https://myapp.example.com,http://localhost:3000")
    app = create_app(handler)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ── Wildcard-Reflection darf nicht passieren ──────────────────────────────────

class TestCorsNoWildcardReflection:

    def test_unknown_origin_gets_no_acao_header(self, client_default):
        """Eine unbekannte Origin darf keinen ACAO-Header bekommen."""
        resp = client_default.get(
            "/conversations",
            headers={"Origin": "https://evil.example.com"},
        )
        acao = resp.headers.get("Access-Control-Allow-Origin", "")
        assert acao != "https://evil.example.com", (
            "Unbekannte Origin wurde gespiegelt – CORS-Wildcard-Reflection aktiv!"
        )

    def test_request_without_origin_gets_no_acao_header(self, client_default):
        """Anfragen ohne Origin-Header dürfen keinen ACAO-Header bekommen."""
        resp = client_default.get("/conversations")
        assert "Access-Control-Allow-Origin" not in resp.headers

    def test_arbitrary_origin_not_reflected_even_if_formatted_like_localhost(self, client_default):
        """localhost-ähnliche aber fremde Origin darf nicht gespiegelt werden."""
        resp = client_default.get(
            "/conversations",
            headers={"Origin": "http://localhost.evil.com"},
        )
        acao = resp.headers.get("Access-Control-Allow-Origin", "")
        assert acao != "http://localhost.evil.com"


# ── Erlaubte Origins werden korrekt gesetzt ───────────────────────────────────

class TestCorsAllowedOrigins:

    def test_allowed_origin_gets_acao_header(self, client_with_origin):
        """Eine konfigurierte Origin bekommt den ACAO-Header."""
        resp = client_with_origin.get(
            "/conversations",
            headers={"Origin": "https://myapp.example.com"},
        )
        assert resp.headers.get("Access-Control-Allow-Origin") == "https://myapp.example.com"

    def test_second_allowed_origin_gets_acao_header(self, client_with_origin):
        resp = client_with_origin.get(
            "/conversations",
            headers={"Origin": "http://localhost:3000"},
        )
        assert resp.headers.get("Access-Control-Allow-Origin") == "http://localhost:3000"

    def test_default_localhost_is_allowed_without_config(self, client_default):
        """Ohne Konfiguration ist http://localhost der Default."""
        resp = client_default.get(
            "/conversations",
            headers={"Origin": "http://localhost"},
        )
        assert resp.headers.get("Access-Control-Allow-Origin") == "http://localhost"

    def test_null_origin_is_not_allowed_by_default(self, client_default):
        resp = client_default.get(
            "/conversations",
            headers={"Origin": "null"},
        )
        assert "Access-Control-Allow-Origin" not in resp.headers

    def test_null_origin_can_be_allowed_explicitly(self, handler, monkeypatch):
        monkeypatch.setenv("CONCLAVE_ALLOWED_ORIGINS", "null")
        app = create_app(handler)
        app.config["TESTING"] = True
        with app.test_client() as client:
            resp = client.get("/conversations", headers={"Origin": "null"})
        assert resp.headers.get("Access-Control-Allow-Origin") == "null"
