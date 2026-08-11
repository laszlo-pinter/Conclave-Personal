# tests/cli/test_bootstrap_universal.py
"""Phase 4 — Beweis: Bootstrap erstellt UniversalAdapter fuer neue Provider."""

from unittest.mock import MagicMock
import pytest

from conclave.domain.agent import Agent
from conclave.cli.bootstrap import _make_adapter


class TestMakeAdapterNative:
    """Bestehende Provider nutzen weiterhin native Adapter."""

    def test_anthropic_returns_native_adapter(self):
        adapter = _make_adapter(Agent(
            id="a1", name="Claude", provider="anthropic",
            model="claude-sonnet-4-20250514",
        ), api_key="sk-ant-test")
        assert adapter is not None
        assert adapter.provider == "anthropic"
        assert type(adapter).__name__ == "AnthropicAdapter"

    def test_openai_returns_native_adapter(self):
        adapter = _make_adapter(Agent(
            id="o1", name="GPT", provider="openai",
            model="gpt-5.4",
        ), api_key="sk-test")
        assert adapter is not None
        assert adapter.provider == "openai"
        assert type(adapter).__name__ == "OpenAIAdapter"


class TestMakeAdapterUniversal:
    """Agenten mit preset/api_url nutzen UniversalAdapter."""

    def test_ollama_preset_returns_universal(self):
        adapter = _make_adapter(Agent(
            id="o1", name="Llama", provider="ollama",
            model="llama3", preset="ollama",
        ), api_key="")
        assert adapter is not None
        assert adapter.provider == "ollama"
        assert type(adapter).__name__ == "UniversalAdapter"

    def test_gemini_preset_returns_universal(self):
        adapter = _make_adapter(Agent(
            id="g1", name="Gemini", provider="gemini",
            model="gemini-2.5-pro", preset="gemini",
        ), api_key="AIza-test")
        assert adapter is not None
        assert adapter.provider == "gemini"
        assert type(adapter).__name__ == "UniversalAdapter"

    def test_custom_api_url_returns_universal(self):
        adapter = _make_adapter(Agent(
            id="c1", name="Custom", provider="custom",
            model="my-model",
            api_url="https://my-server.com/v1/chat",
            response_path="result.text",
        ), api_key="my-key")
        assert adapter is not None
        assert adapter.provider == "custom"
        assert type(adapter).__name__ == "UniversalAdapter"

    def test_mistral_preset_returns_universal(self):
        adapter = _make_adapter(Agent(
            id="m1", name="Mistral", provider="mistral",
            model="mistral-large-latest", preset="mistral",
        ), api_key="mk-test")
        assert adapter is not None
        assert adapter.provider == "mistral"

    def test_ollama_no_key_required(self):
        """Ollama braucht keinen API-Key."""
        adapter = _make_adapter(Agent(
            id="o1", name="Llama", provider="ollama",
            model="llama3", preset="ollama",
        ), api_key="")
        assert adapter is not None

    def test_universal_has_correct_response_path(self):
        adapter = _make_adapter(Agent(
            id="g1", name="Gemini", provider="gemini",
            model="gemini-2.5-pro", preset="gemini",
        ), api_key="AIza-test")
        assert "candidates" in adapter._response_path
