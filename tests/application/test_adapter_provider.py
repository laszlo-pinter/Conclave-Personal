# tests/application/test_adapter_provider.py

"""Provider muss als explizites Attribut auf jedem Adapter verfuegbar sein."""

from unittest.mock import patch

import pytest


def test_anthropic_adapter_has_provider():
    pytest.importorskip("anthropic")
    from conclave.infrastructure.anthropic.adapter import AnthropicAdapter
    with patch("conclave.infrastructure.anthropic.adapter.anthropic.Anthropic"):
        adapter = AnthropicAdapter(api_key="test")
    assert adapter.provider == "anthropic"


def test_openai_adapter_has_provider():
    pytest.importorskip("openai")
    from conclave.infrastructure.openai.adapter import OpenAIAdapter
    with patch("conclave.infrastructure.openai.adapter.openai.OpenAI"):
        adapter = OpenAIAdapter(api_key="test")
    assert adapter.provider == "openai"


def test_async_anthropic_adapter_has_provider():
    pytest.importorskip("anthropic")
    from conclave.infrastructure.anthropic.async_adapter import AsyncAnthropicAdapter
    with patch("conclave.infrastructure.anthropic.async_adapter.anthropic.AsyncAnthropic"):
        adapter = AsyncAnthropicAdapter(api_key="test")
    assert adapter.provider == "anthropic"


def test_async_openai_adapter_has_provider():
    pytest.importorskip("openai")
    from conclave.infrastructure.openai.async_adapter import AsyncOpenAIAdapter
    with patch("conclave.infrastructure.openai.async_adapter.openai.AsyncOpenAI"):
        adapter = AsyncOpenAIAdapter(api_key="test")
    assert adapter.provider == "openai"


def test_invoke_uses_adapter_provider_not_model(service):
    """conversation_flow nutzt adapter.provider, nicht adapter._model."""
    from unittest.mock import MagicMock
    from conclave.application.adapter_registry import AdapterRegistry
    from conclave.domain.participant import ParticipantType

    conv = service.create_conversation()
    service.register_participant(conv.id, "p1", ParticipantType.MODEL, "Claude")
    service.add_user_message(conv.id, "Hallo")

    adapter = MagicMock()
    adapter.provider = "anthropic"
    adapter._model = "claude-sonnet-4-20250514"
    adapter.complete.return_value = "Antwort"

    registry = AdapterRegistry()
    registry.register("p1", adapter)
    service.set_adapter_registry(registry)

    # Audit-Repo setzen um Provider zu verifizieren
    from conclave.infrastructure.sqlite.audit_repository import SQLiteAuditRepository
    audit_repo = SQLiteAuditRepository(service._conversation_repository._connection)
    service.set_audit_repository(audit_repo)

    service.invoke_participant(conv.id, "p1")

    entries = audit_repo.list_by_conversation(conv.id)
    assert entries[0].provider == "anthropic"
    assert entries[0].model == "claude-sonnet-4-20250514"
