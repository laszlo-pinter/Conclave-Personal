# tests/application/test_async_conversation_flow.py

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from conclave.application.conversation_flow import ConversationFlowService
from conclave.application.adapter_registry import AdapterRegistry
from conclave.domain.errors import AdapterNotFound, ParticipantNotRegistered
from conclave.domain.participant import ParticipantType


@pytest.mark.asyncio
async def test_async_invoke_participant(service):
    """async_invoke_participant ruft async adapter.complete() auf."""
    conversation = service.create_conversation()
    service.register_participant(conversation.id, "model-a", ParticipantType.MODEL, "Claude")

    adapter = MagicMock()
    adapter.complete = AsyncMock(return_value="Async Antwort")

    registry = AdapterRegistry()
    registry.register("model-a", adapter)
    service.set_adapter_registry(registry)

    service.add_user_message(conversation.id, "Hallo")

    updated = await service.async_invoke_participant(conversation.id, "model-a")

    adapter.complete.assert_awaited_once()
    assert updated.messages[-1].content == "Async Antwort"


@pytest.mark.asyncio
async def test_async_invoke_participant_without_adapter_raises(service):
    conversation = service.create_conversation()
    service.register_participant(conversation.id, "model-a", ParticipantType.MODEL, "Claude")

    with pytest.raises(AdapterNotFound):
        await service.async_invoke_participant(conversation.id, "model-a")


@pytest.mark.asyncio
async def test_async_invoke_unknown_participant_raises(service):
    conversation = service.create_conversation()

    adapter = MagicMock()
    adapter.complete = AsyncMock(return_value="x")
    registry = AdapterRegistry()
    registry.register("unknown", adapter)
    service.set_adapter_registry(registry)

    with pytest.raises(ParticipantNotRegistered):
        await service.async_invoke_participant(conversation.id, "unknown")


@pytest.mark.asyncio
async def test_async_invoke_with_explicit_adapter(service):
    """Explizit übergebener Adapter hat Vorrang vor Registry."""
    conversation = service.create_conversation()
    service.register_participant(conversation.id, "model-a", ParticipantType.MODEL, "Claude")
    service.add_user_message(conversation.id, "Hallo")

    adapter = MagicMock()
    adapter.complete = AsyncMock(return_value="Direkte Antwort")

    updated = await service.async_invoke_participant(conversation.id, "model-a", adapter=adapter)
    assert updated.messages[-1].content == "Direkte Antwort"


@pytest.mark.asyncio
async def test_async_stream_participant(service):
    """async_stream_participant yieldet Tokens und speichert Message."""
    conversation = service.create_conversation()
    service.register_participant(conversation.id, "model-a", ParticipantType.MODEL, "Claude")
    service.add_user_message(conversation.id, "Hallo")

    async def fake_stream(conv, part):
        for token in ["Hal", "lo", " Welt"]:
            yield token

    adapter = MagicMock()
    adapter.stream = fake_stream
    adapter.complete = AsyncMock(return_value="fallback")

    registry = AdapterRegistry()
    registry.register("model-a", adapter)
    service.set_adapter_registry(registry)

    tokens = []
    async for token in service.async_stream_participant(conversation.id, "model-a"):
        tokens.append(token)

    assert tokens == ["Hal", "lo", " Welt"]

    # Message wurde gespeichert
    conv = service.load_conversation(conversation.id)
    assert conv.messages[-1].content == "Hallo Welt"
