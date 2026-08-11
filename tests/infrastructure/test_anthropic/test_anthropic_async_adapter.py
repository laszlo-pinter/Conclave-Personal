# tests/infrastructure/test_anthropic/test_anthropic_async_adapter.py

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
pytest.importorskip("anthropic")

from conclave.domain.conversation import Conversation
from conclave.domain.message import Message, MessageAuthorType
from conclave.domain.participant import Participant, ParticipantType
from conclave.application.ports import AsyncModelAdapter, AsyncStreamingModelAdapter


def make_conversation(*messages: tuple[MessageAuthorType, str]) -> Conversation:
    conversation_id = str(uuid.uuid4())
    conversation = Conversation(id=conversation_id)
    for i, (author_type, content) in enumerate(messages, start=1):
        msg = Message(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            author_type=author_type,
            author_id=None if author_type == MessageAuthorType.USER else "model-a",
            content=content,
            sequence=i,
            created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )
        conversation.messages.append(msg)
    return conversation


def make_participant() -> Participant:
    return Participant(
        id="model-a",
        conversation_id=str(uuid.uuid4()),
        participant_type=ParticipantType.MODEL,
        name="Claude",
    )


def make_mock_response(text: str):
    response = MagicMock()
    response.content = [MagicMock(text=text)]
    return response


def test_async_anthropic_adapter_satisfies_async_protocol():
    from conclave.infrastructure.anthropic.async_adapter import AsyncAnthropicAdapter
    with patch("conclave.infrastructure.anthropic.async_adapter.anthropic.AsyncAnthropic"):
        adapter = AsyncAnthropicAdapter(api_key="test-key")
        assert isinstance(adapter, AsyncModelAdapter)
        assert isinstance(adapter, AsyncStreamingModelAdapter)


@pytest.mark.asyncio
async def test_async_complete_returns_response():
    from conclave.infrastructure.anthropic.async_adapter import AsyncAnthropicAdapter
    with patch("conclave.infrastructure.anthropic.async_adapter.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = mock_cls.return_value
        mock_client.messages.create = AsyncMock(return_value=make_mock_response("Hallo async"))

        adapter = AsyncAnthropicAdapter(api_key="test-key")
        conversation = make_conversation((MessageAuthorType.USER, "Hallo"))
        result = await adapter.complete(conversation, make_participant())

        assert result == "Hallo async"


@pytest.mark.asyncio
async def test_async_complete_passes_system_prompt():
    from conclave.infrastructure.anthropic.async_adapter import AsyncAnthropicAdapter
    with patch("conclave.infrastructure.anthropic.async_adapter.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = mock_cls.return_value
        mock_client.messages.create = AsyncMock(return_value=make_mock_response("ok"))

        adapter = AsyncAnthropicAdapter(api_key="test-key", system_prompt="Sei präzise.")
        conversation = make_conversation((MessageAuthorType.USER, "Hallo"))
        await adapter.complete(conversation, make_participant())

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["system"] == "Sei präzise."


@pytest.mark.asyncio
async def test_async_stream_yields_tokens():
    from conclave.infrastructure.anthropic.async_adapter import AsyncAnthropicAdapter
    with patch("conclave.infrastructure.anthropic.async_adapter.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = mock_cls.return_value

        # Simulate async stream context manager
        mock_event_1 = MagicMock(type="content_block_delta", delta=MagicMock(type="text_delta", text="Hal"))
        mock_event_2 = MagicMock(type="content_block_delta", delta=MagicMock(type="text_delta", text="lo"))
        mock_event_3 = MagicMock(type="message_stop")

        async def fake_stream_iter():
            for event in [mock_event_1, mock_event_2, mock_event_3]:
                yield event

        stream_cm = MagicMock()
        stream_cm.__aenter__ = AsyncMock(return_value=fake_stream_iter())
        stream_cm.__aexit__ = AsyncMock(return_value=False)
        mock_client.messages.stream.return_value = stream_cm

        adapter = AsyncAnthropicAdapter(api_key="test-key")
        conversation = make_conversation((MessageAuthorType.USER, "Hallo"))
        tokens = []
        async for token in adapter.stream(conversation, make_participant()):
            tokens.append(token)

        assert tokens == ["Hal", "lo"]
