# tests/api/test_universal_api.py
"""Phase 5 — Beweis: API unterstuetzt Presets, Agent-Test, neue Felder."""

import pytest
from unittest.mock import patch, MagicMock

from conclave.api.app import create_app
from conclave.cli.handler import CLIHandler


@pytest.fixture()
def client(tmp_path):
    """Flask Test-Client mit frischer DB."""
    import sqlite3
    from conclave.infrastructure.sqlite.schema import initialize_schema
    from conclave.infrastructure.sqlite.conversation_repository import SQLiteConversationRepository
    from conclave.infrastructure.sqlite.message_repository import SQLiteMessageRepository
    from conclave.infrastructure.sqlite.participant_repository import SQLiteParticipantRepository
    from conclave.application.conversation_flow import ConversationFlowService
    from conclave.application.agent_service import AgentService
    from conclave.infrastructure.sqlite.agent_repository import SQLiteAgentRepository
    from conclave.infrastructure.crypto import NullCryptoService

    conn = sqlite3.connect(str(tmp_path / "test.db"))
    initialize_schema(conn)
    crypto = NullCryptoService()
    service = ConversationFlowService(
        SQLiteConversationRepository(conn),
        SQLiteMessageRepository(conn, crypto=crypto),
        SQLiteParticipantRepository(conn),
    )
    agent_svc = AgentService(SQLiteAgentRepository(conn, crypto))
    handler = CLIHandler(service, agent_service=agent_svc)
    app = create_app(handler)
    app.testing = True
    with app.test_client() as c:
        yield c


class TestPresetsEndpoint:

    def test_get_presets(self, client):
        """GET /presets → Liste aller Presets."""
        resp = client.get("/presets")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "presets" in data
        names = {p["name"] for p in data["presets"]}
        assert "ollama" in names
        assert "gemini" in names

    def test_preset_has_required_fields(self, client):
        resp = client.get("/presets")
        p = resp.get_json()["presets"][0]
        assert "api_url" in p
        assert "response_path" in p
        assert "models" in p


class TestAgentWithPreset:

    def test_create_agent_with_preset(self, client):
        """POST /agents mit preset-Feld → Agent gespeichert."""
        resp = client.post("/agents", json={
            "id": "llama1", "name": "Llama", "provider": "ollama",
            "model": "llama3", "preset": "ollama",
        })
        assert resp.status_code == 201

        resp = client.get("/agents/llama1")
        data = resp.get_json()
        assert data["provider"] == "ollama"
        assert data.get("preset") == "ollama"

    def test_create_agent_with_custom_url(self, client):
        resp = client.post("/agents", json={
            "id": "c1", "name": "Custom", "provider": "custom",
            "model": "my-model", "api_url": "https://my-server.com/v1",
            "response_path": "result.text",
        })
        assert resp.status_code == 201

        resp = client.get("/agents/c1")
        data = resp.get_json()
        assert data.get("api_url") == "https://my-server.com/v1"
        assert data.get("response_path") == "result.text"

    def test_create_agent_with_api_key(self, client):
        """API-Key wird gespeichert (verschluesselt) und nicht im Klartext zurueckgegeben."""
        resp = client.post("/agents", json={
            "id": "g1", "name": "Gemini", "provider": "gemini",
            "model": "gemini-pro", "preset": "gemini",
            "api_key": "AIza-secret",
        })
        assert resp.status_code == 201

        resp = client.get("/agents/g1")
        data = resp.get_json()
        assert data.get("api_key_set") is True
        # Klartext-Key darf nicht zurueckgegeben werden
        assert "AIza-secret" not in str(data)


class TestAgentTest:

    @patch("conclave.cli.handler.CLIHandler._test_agent_connection")
    def test_agent_test_endpoint(self, mock_test, client):
        """POST /agents/<id>/test → testet Verbindung."""
        mock_test.return_value = {"success": True, "message": "OK"}
        client.post("/agents", json={
            "id": "t1", "name": "Test", "provider": "anthropic",
            "model": "claude-sonnet-4-20250514",
        })
        resp = client.post("/agents/t1/test")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
