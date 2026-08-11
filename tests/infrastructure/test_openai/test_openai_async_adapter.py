# tests/infrastructure/test_openai/test_openai_async_adapter.py

from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
pytest.importorskip("openai")

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
        name="GPT",
    )


def test_async_openai_adapter_satisfies_async_protocol():
    from conclave.infrastructure.openai.async_adapter import AsyncOpenAIAdapter
    with patch("conclave.infrastructure.openai.async_adapter.openai.AsyncOpenAI"):
        adapter = AsyncOpenAIAdapter(api_key="test-key")
        assert isinstance(adapter, AsyncModelAdapter)
        assert isinstance(adapter, AsyncStreamingModelAdapter)


@pytest.mark.asyncio
async def test_async_complete_returns_response():
    from conclave.infrastructure.openai.async_adapter import AsyncOpenAIAdapter
    with patch("conclave.infrastructure.openai.async_adapter.openai.AsyncOpenAI") as mock_cls:
        mock_response = MagicMock()
        mock_response.output_text = "Hallo async"
        mock_cls.return_value.responses.create = AsyncMock(return_value=mock_response)

        adapter = AsyncOpenAIAdapter(api_key="test-key")
        conversation = make_conversation((MessageAuthorType.USER, "Hallo"))
        result = await adapter.complete(conversation, make_participant())

        assert result == "Hallo async"


@pytest.mark.asyncio
async def test_async_complete_passes_system_prompt():
    from conclave.infrastructure.openai.async_adapter import AsyncOpenAIAdapter
    with patch("conclave.infrastructure.openai.async_adapter.openai.AsyncOpenAI") as mock_cls:
        mock_response = MagicMock()
        mock_response.output_text = "ok"
        mock_cls.return_value.responses.create = AsyncMock(return_value=mock_response)

        adapter = AsyncOpenAIAdapter(api_key="test-key", system_prompt="Sei praezise.")
        conversation = make_conversation((MessageAuthorType.USER, "Hallo"))
        await adapter.complete(conversation, make_participant())

        call_kwargs = mock_cls.return_value.responses.create.call_args.kwargs
        assert call_kwargs["instructions"] == "Sei praezise."


@pytest.mark.asyncio
async def test_async_stream_yields_tokens():
    from conclave.infrastructure.openai.async_adapter import AsyncOpenAIAdapter
    with patch("conclave.infrastructure.openai.async_adapter.openai.AsyncOpenAI") as mock_cls:
        async def fake_stream():
            for evt in [
                MagicMock(type="response.output_text.delta", delta="Hal"),
                MagicMock(type="response.output_text.delta", delta="lo"),
                MagicMock(type="response.completed"),
            ]:
                yield evt

        mock_cls.return_value.responses.create = AsyncMock(return_value=fake_stream())

        adapter = AsyncOpenAIAdapter(api_key="test-key")
        conversation = make_conversation((MessageAuthorType.USER, "Hallo"))
        tokens = []
        async for token in adapter.stream(conversation, make_participant()):
            tokens.append(token)

        assert tokens == ["Hal", "lo"]
