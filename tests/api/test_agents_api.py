# tests/api/test_agents_api.py

import json
import pytest
pytest.importorskip("flask")

from unittest.mock import MagicMock
from conclave.api.app import create_app
from conclave.cli.handler import CLIResult


@pytest.fixture
def handler():
    h = MagicMock()
    h.list_agents.return_value = CLIResult(success=True, message="ok", data={"agents": [
        {"id": "a1", "name": "Claude", "provider": "anthropic", "model": "claude-sonnet-4-20250514",
         "role": "analytiker", "topic": "KI", "system_prompt": "Sei präzise.", "created_at": "2026-01-01T00:00:00+00:00"},
    ]})
    h.get_agent.return_value = CLIResult(success=True, message="ok", data={
        "id": "a1", "name": "Claude", "provider": "anthropic", "model": "claude-sonnet-4-20250514",
        "role": "analytiker", "topic": "KI", "system_prompt": "Sei präzise.", "created_at": "2026-01-01T00:00:00+00:00",
    })
    h.create_agent.return_value = CLIResult(success=True, message="Erstellt", data={"id": "a1"})
    h.update_agent.return_value = CLIResult(success=True, message="Aktualisiert", data={"id": "a1"})
    h.delete_agent.return_value = CLIResult(success=True, message="Gelöscht", data={"id": "a1"})
    return h


@pytest.fixture
def client(handler):
    app = create_app(handler)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_get_agents_returns_200(client):
    assert client.get("/agents").status_code == 200


def test_get_agents_returns_list(client):
    body = json.loads(client.get("/agents").data)
    assert len(body["agents"]) == 1
    assert body["agents"][0]["id"] == "a1"


def test_get_single_agent_returns_200(client):
    assert client.get("/agents/a1").status_code == 200


def test_get_unknown_agent_returns_404(client, handler):
    handler.get_agent.return_value = CLIResult(success=False, message="Nicht gefunden.")
    assert client.get("/agents/unbekannt").status_code == 404


def test_post_agent_returns_201(client):
    res = client.post("/agents", json={
        "id": "a1", "name": "Claude", "provider": "anthropic", "model": "claude-sonnet-4-20250514"
    })
    assert res.status_code == 201


def test_post_agent_missing_fields_returns_400(client):
    assert client.post("/agents", json={"name": "Claude"}).status_code == 400


def test_put_agent_returns_200(client):
    res = client.put("/agents/a1", json={
        "name": "Claude Neu", "provider": "anthropic",
        "model": "claude-sonnet-4-20250514", "role": "kritiker"
    })
    assert res.status_code == 200


def test_put_unknown_agent_returns_404(client, handler):
    handler.update_agent.return_value = CLIResult(success=False, message="Nicht gefunden.")
    res = client.put("/agents/unbekannt", json={
        "name": "X", "provider": "anthropic", "model": "m"
    })
    assert res.status_code == 404


def test_delete_agent_returns_204(client):
    assert client.delete("/agents/a1").status_code == 204


def test_delete_unknown_agent_returns_404(client, handler):
    handler.delete_agent.return_value = CLIResult(success=False, message="Nicht gefunden.")
    assert client.delete("/agents/unbekannt").status_code == 404
