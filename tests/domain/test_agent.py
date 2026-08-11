# tests/domain/test_agent.py

import pytest
from conclave.domain.agent import Agent


def test_agent_creates_with_required_fields():
    a = Agent(id="claude1", name="Claude", provider="anthropic", model="claude-sonnet-4-20250514")
    assert a.id == "claude1"
    assert a.name == "Claude"
    assert a.created_at is not None


def test_agent_optional_fields_default_empty():
    a = Agent(id="a1", name="Test", provider="anthropic", model="claude-haiku-4-5-20251001")
    assert a.role == ""
    assert a.topic == ""
    assert a.system_prompt == ""


def test_agent_raises_for_empty_id():
    with pytest.raises(ValueError, match="id"):
        Agent(id="  ", name="Test", provider="anthropic", model="gpt-4o")


def test_agent_raises_for_empty_name():
    with pytest.raises(ValueError, match="name"):
        Agent(id="a1", name="", provider="anthropic", model="gpt-4o")


def test_agent_accepts_openai_provider():
    a = Agent(id="gpt1", name="GPT", provider="openai", model="gpt-4o")
    assert a.provider == "openai"


# ── Phase 1: Provider-Config-Felder ──────────────────────────────────

def test_agent_accepts_any_provider():
    """Provider ist nicht mehr auf anthropic/openai beschraenkt."""
    a = Agent(id="g1", name="Gemini", provider="gemini", model="gemini-pro")
    assert a.provider == "gemini"


def test_agent_accepts_ollama_provider():
    a = Agent(id="o1", name="Llama", provider="ollama", model="llama3")
    assert a.provider == "ollama"


def test_agent_accepts_custom_provider():
    a = Agent(id="c1", name="Custom", provider="custom", model="my-model")
    assert a.provider == "custom"


def test_agent_raises_for_empty_provider():
    with pytest.raises(ValueError, match="provider"):
        Agent(id="a1", name="Test", provider="", model="x")


def test_agent_with_provider_config_fields():
    """Neue Felder: preset, api_url, response_path, message_format."""
    a = Agent(
        id="g1", name="Gemini", provider="gemini", model="gemini-pro",
        preset="gemini",
        api_url="https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent",
        response_path="candidates[0].content.parts[0].text",
        message_format="gemini",
    )
    assert a.preset == "gemini"
    assert a.api_url.startswith("https://")
    assert a.response_path == "candidates[0].content.parts[0].text"
    assert a.message_format == "gemini"


def test_agent_provider_config_defaults_empty():
    """Neue Felder haben Default-Werte (leer)."""
    a = Agent(id="a1", name="Test", provider="anthropic", model="claude-sonnet-4-20250514")
    assert a.preset == ""
    assert a.api_url == ""
    assert a.response_path == ""
    assert a.message_format == "standard"


def test_agent_with_preset_ollama():
    a = Agent(
        id="o1", name="Llama", provider="ollama", model="llama3",
        preset="ollama",
        api_url="http://localhost:11434/api/chat",
        response_path="message.content",
    )
    assert a.preset == "ollama"
