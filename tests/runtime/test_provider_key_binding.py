"""R3 (conclave#33): Keys aus Umgebung bzw. Konfiguration gehen nur an den Host ihres Presets.

Ein Agent mit eigener Adresse bekommt keinen Fallback-Key; aendern sich Adresse,
Preset oder Provider, wird ein gespeicherter Key verworfen, ausser er wird neu
eingegeben.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from conclave.cli.config import ConclaveConfig
from conclave.domain.agent import Agent
from conclave.domain.conversation import Conversation
from conclave.domain.message import Message, MessageAuthorType
from conclave.domain.participant import Participant, ParticipantType

FOREIGN = "https://gateway.invalid/v1/chat/completions"


def _conversation():
    conv = Conversation(id="c1", status="active", topic="t")
    conv.messages = [Message(id="m1", conversation_id="c1", author_type=MessageAuthorType.USER, author_id=None,
                             content="Hallo", sequence=1, created_at=datetime.now(UTC))]
    return conv


def _participant(agent_id):
    return Participant(id=agent_id, conversation_id="c1", participant_type=ParticipantType.MODEL, name="A")


def _sent_headers(agent, config):
    """Baut den Adapter wie der Server und schickt eine Anfrage an ein gemocktes httpx."""
    from conclave.cli.bootstrap import _build_adapter_for_agent
    adapter = _build_adapter_for_agent(agent, config)
    if adapter is None:
        return None
    response = MagicMock(status_code=200)
    response.json.return_value = {"choices": [{"message": {"content": "ok"}}], "usage": {}}
    with patch("conclave.infrastructure.universal.adapter.httpx") as httpx_mock, \
            patch("conclave.infrastructure.universal.adapter._validate_url"):
        httpx_mock.post.return_value = response
        adapter.complete(_conversation(), _participant(agent.id))
        return httpx_mock.post.call_args.kwargs["headers"]


@pytest.fixture
def config():
    return ConclaveConfig(openai_api_key="sk-env-openai")


def test_foreign_url_gets_no_fallback_key(config, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-openai")
    agent = Agent(id="a1", name="A", provider="openai", model="gpt-x", preset="openai", api_url=FOREIGN)
    headers = _sent_headers(agent, config)
    assert headers is None or "Authorization" not in headers


def test_preset_url_still_uses_the_fallback_key(config):
    agent = Agent(id="a2", name="A", provider="openai", model="gpt-x", preset="openai")
    assert _sent_headers(agent, config)["Authorization"] == "Bearer sk-env-openai"
    same_host = Agent(id="a3", name="A", provider="openai", model="gpt-x", preset="openai",
                      api_url="https://api.openai.com/v1/chat/completions")
    assert _sent_headers(same_host, config)["Authorization"] == "Bearer sk-env-openai"


def test_provider_key_does_not_go_to_another_presets_host(monkeypatch):
    """OpenAI-Key aus der Konfiguration, aber Preset DeepSeek: der Key bleibt bei OpenAI."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    from conclave.cli.provider_keys import fallback_key
    agent = Agent(id="a4", name="A", provider="openai", model="m", preset="deepseek")
    assert fallback_key(agent, {"openai": "sk-env-openai"}) == ""


def test_env_key_of_a_preset_only_for_its_host(monkeypatch):
    from conclave.cli.provider_keys import fallback_key
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deep")
    official = Agent(id="d1", name="D", provider="deepseek", model="deepseek-chat", preset="deepseek")
    foreign = Agent(id="d2", name="D", provider="deepseek", model="deepseek-chat", preset="deepseek",
                    api_url="http://127.0.0.1:9999/v1/chat/completions")
    assert fallback_key(official, {}) == "sk-deep"
    assert fallback_key(foreign, {}) == ""


def test_native_agent_without_url_keeps_its_provider_key():
    from conclave.cli.provider_keys import fallback_key
    agent = Agent(id="n1", name="N", provider="anthropic", model="claude-x")
    assert fallback_key(agent, {"anthropic": "sk-ant"}) == "sk-ant"


def test_api_key_set_shows_false_for_a_foreign_url(agent_service, monkeypatch):
    from conclave.cli.handler import CLIHandler
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-openai")
    handler = CLIHandler(None, agent_service=agent_service, provider_fallback_keys={"openai": "sk-env-openai"})
    agent = Agent(id="f1", name="F", provider="openai", model="m", preset="openai", api_url=FOREIGN)
    agent_service.create_agent(agent)
    assert handler.list_agents().data["agents"][0]["api_key_set"] is False


@pytest.mark.parametrize("change", [{"api_url": FOREIGN}, {"provider": "deepseek", "preset": ""},
                                    {"preset": "deepseek"}])
def test_changed_target_drops_the_stored_key(agent_service, change):
    from dataclasses import replace

    from conclave.cli.handler import CLIHandler
    handler = CLIHandler(None, agent_service=agent_service)
    stored = Agent(id="k1", name="K", provider="openai", model="m", preset="openai", api_key="sk-stored")
    agent_service.create_agent(stored)
    assert handler.update_agent(replace(stored, api_key="", **change)).success
    assert agent_service.get_agent("k1").api_key == ""


def test_unchanged_target_keeps_the_stored_key_and_new_key_is_used(agent_service):
    from dataclasses import replace

    from conclave.cli.handler import CLIHandler
    handler = CLIHandler(None, agent_service=agent_service)
    stored = Agent(id="k2", name="K", provider="openai", model="m", preset="openai", api_key="sk-stored")
    agent_service.create_agent(stored)
    assert handler.update_agent(replace(stored, api_key="", name="Neu")).success
    assert agent_service.get_agent("k2").api_key == "sk-stored"
    assert handler.update_agent(replace(stored, api_key="sk-neu", api_url=FOREIGN)).success
    assert agent_service.get_agent("k2").api_key == "sk-neu"                    # neu eingegeben: gilt


def test_same_host_by_other_means_keeps_the_stored_key(agent_service):
    """CLI-Bearbeitung ohne --preset/--api-url: nativer Adapter, gleicher Host, Key bleibt."""
    from dataclasses import replace

    from conclave.cli.handler import CLIHandler
    handler = CLIHandler(None, agent_service=agent_service)
    stored = Agent(id="k3", name="K", provider="anthropic", model="m", preset="anthropic",
                   api_url="https://api.anthropic.com/v1/messages", api_key="sk-stored")
    agent_service.create_agent(stored)
    assert handler.update_agent(replace(stored, api_key="", preset="", api_url="")).success
    assert agent_service.get_agent("k3").api_key == "sk-stored"
