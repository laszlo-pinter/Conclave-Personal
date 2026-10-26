# tests/api/test_agent_key_preservation.py

"""Regression: Agent bearbeiten darf den gespeicherten API-Key nicht loeschen.

Die UI zeigt gespeicherte Keys nie an und schickt beim Speichern nur einen neu
eingegebenen Key mit. Frueher setzte PUT /agents/<id> den Key dann auf "".
"""

import pytest
pytest.importorskip("flask")

from conclave.api.app import create_app
from conclave.application.agent_service import AgentService
from conclave.cli.handler import CLIHandler
from conclave.domain.agent import Agent
from conclave.infrastructure.sqlite.agent_repository import SQLiteAgentRepository

BASE = {"name": "Claude", "provider": "anthropic", "model": "claude-sonnet-5", "preset": "anthropic",
        "api_url": "https://api.anthropic.com/v1/messages", "response_path": "content[0].text",
        "message_format": "standard", "role": "", "topic": "", "system_prompt": ""}


@pytest.fixture
def setup(db_connection, crypto, service):
    agents = AgentService(SQLiteAgentRepository(db_connection, crypto))
    handler = CLIHandler(service, agent_service=agents)
    app = create_app(handler, agent_service=agents)
    app.config["TESTING"] = True
    client = app.test_client()
    assert client.post("/agents", json={"id": "claude", **BASE, "api_key": "sk-original"}).status_code == 201
    return client, agents, handler


def test_ui_save_without_key_keeps_stored_key(setup):
    client, agents, _ = setup
    resp = client.put("/agents/claude", json={**BASE, "topic": "neu"})
    assert resp.status_code == 200
    stored = agents.get_agent("claude")
    assert stored.api_key == "sk-original"
    assert stored.topic == "neu"


def test_empty_key_field_keeps_stored_key(setup):
    client, agents, _ = setup
    client.put("/agents/claude", json={**BASE, "api_key": ""})
    assert agents.get_agent("claude").api_key == "sk-original"


def test_new_key_replaces_stored_key(setup):
    client, agents, _ = setup
    client.put("/agents/claude", json={**BASE, "api_key": "sk-neu"})
    assert agents.get_agent("claude").api_key == "sk-neu"


def test_key_is_removed_only_explicitly(setup):
    client, agents, _ = setup
    client.put("/agents/claude", json={**BASE, "clear_api_key": True})
    assert agents.get_agent("claude").api_key == ""


def test_set_agent_key_keeps_preset_and_url(setup):
    _, agents, handler = setup
    assert handler.set_agent_key("claude", "sk-cli").success
    stored = agents.get_agent("claude")
    assert stored.api_key == "sk-cli"
    assert stored.preset == "anthropic"
    assert stored.api_url == BASE["api_url"]
    assert stored.response_path == BASE["response_path"]


def test_cli_edit_without_key_keeps_stored_key(setup):
    _, agents, handler = setup
    agent = Agent(id="claude", name="Claude 2", provider="anthropic", model="claude-sonnet-5", api_key="")
    assert handler.update_agent(agent).success
    assert agents.get_agent("claude").api_key == "sk-original"
