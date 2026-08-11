# tests/infrastructure/test_openai/test_openai_adapter.py

from unittest.mock import MagicMock, patch
import uuid
from datetime import datetime, timezone

import pytest
pytest.importorskip("openai")

from conclave.domain.conversation import Conversation
from conclave.domain.message import Message, MessageAuthorType
from conclave.domain.participant import Participant, ParticipantType
from conclave.infrastructure.openai.adapter import OpenAIAdapter
from conclave.application.ports import ModelAdapter


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
            created_at=datetime.now(timezone.utc),
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


def make_mock_response(text: str):
    """Mock fuer OpenAI Responses API."""
    response = MagicMock()
    response.output_text = text
    response.usage = MagicMock(input_tokens=10, output_tokens=5)
    return response


def test_openai_adapter_satisfies_protocol():
    with patch("conclave.infrastructure.openai.adapter.openai.OpenAI"):
        adapter = OpenAIAdapter(api_key="test-key")
        assert isinstance(adapter, ModelAdapter)


def test_complete_returns_model_response():
    with patch("conclave.infrastructure.openai.adapter.openai.OpenAI") as mock_openai:
        mock_openai.return_value.responses.create.return_value = make_mock_response("Hallo vom Modell")

        adapter = OpenAIAdapter(api_key="test-key")
        conversation = make_conversation((MessageAuthorType.USER, "Hallo!"))
        result = adapter.complete(conversation, make_participant())

        assert result == "Hallo vom Modell"


def test_messages_are_mapped_to_openai_format():
    with patch("conclave.infrastructure.openai.adapter.openai.OpenAI") as mock_openai:
        mock_openai.return_value.responses.create.return_value = make_mock_response("ok")

        adapter = OpenAIAdapter(api_key="test-key")
        conversation = make_conversation(
            (MessageAuthorType.USER, "Erste Frage"),
            (MessageAuthorType.MODEL, "Erste Antwort"),
            (MessageAuthorType.USER, "Zweite Frage"),
        )
        adapter.complete(conversation, make_participant())

        call_kwargs = mock_openai.return_value.responses.create.call_args.kwargs
        assert call_kwargs["input"] == [
            {"role": "user",      "content": "Erste Frage"},
            {"role": "assistant", "content": "Erste Antwort"},
            {"role": "user",      "content": "Zweite Frage"},
        ]


def test_system_prompt_is_prepended_when_set():
    with patch("conclave.infrastructure.openai.adapter.openai.OpenAI") as mock_openai:
        mock_openai.return_value.responses.create.return_value = make_mock_response("ok")

        adapter = OpenAIAdapter(api_key="test-key", system_prompt="Du bist ein Assistent.")
        conversation = make_conversation((MessageAuthorType.USER, "Hallo"))
        adapter.complete(conversation, make_participant())

        call_kwargs = mock_openai.return_value.responses.create.call_args.kwargs
        assert call_kwargs["instructions"] == "Du bist ein Assistent."


def test_no_system_prompt_by_default():
    with patch("conclave.infrastructure.openai.adapter.openai.OpenAI") as mock_openai:
        mock_openai.return_value.responses.create.return_value = make_mock_response("ok")

        adapter = OpenAIAdapter(api_key="test-key")
        conversation = make_conversation((MessageAuthorType.USER, "Hallo"))
        adapter.complete(conversation, make_participant())

        call_kwargs = mock_openai.return_value.responses.create.call_args.kwargs
        assert "instructions" not in call_kwargs


def test_model_and_max_tokens_are_forwarded():
    with patch("conclave.infrastructure.openai.adapter.openai.OpenAI") as mock_openai:
        mock_openai.return_value.responses.create.return_value = make_mock_response("ok")

        adapter = OpenAIAdapter(api_key="test-key", model="gpt-4o", max_tokens=512)
        conversation = make_conversation((MessageAuthorType.USER, "Hallo"))
        adapter.complete(conversation, make_participant())

        call_kwargs = mock_openai.return_value.responses.create.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4o"


# ── Streaming ──────────────────────────────────────────────────────────────


def make_mock_stream_event(event_type: str, delta: str = ""):
    """Erzeugt einen Mock-Event fuer OpenAI Responses Streaming."""
    event = MagicMock()
    event.type = event_type
    event.delta = delta
    if event_type == "response.completed":
        event.response = MagicMock()
        event.response.usage = MagicMock(input_tokens=10, output_tokens=5)
    return event


def test_openai_adapter_satisfies_streaming_protocol():
    from conclave.application.ports import StreamingModelAdapter
    with patch("conclave.infrastructure.openai.adapter.openai.OpenAI"):
        adapter = OpenAIAdapter(api_key="test-key")
        assert isinstance(adapter, StreamingModelAdapter)


def test_stream_yields_tokens():
    with patch("conclave.infrastructure.openai.adapter.openai.OpenAI") as mock_openai:
        events = [
            make_mock_stream_event("response.output_text.delta", "Hal"),
            make_mock_stream_event("response.output_text.delta", "lo"),
            make_mock_stream_event("response.output_text.delta", " Welt"),
            make_mock_stream_event("response.completed"),
        ]
        mock_openai.return_value.responses.create.return_value = iter(events)

        adapter = OpenAIAdapter(api_key="test-key")
        conversation = make_conversation((MessageAuthorType.USER, "Hallo"))
        tokens = list(adapter.stream(conversation, make_participant()))

        assert tokens == ["Hal", "lo", " Welt"]


def test_stream_ignores_chunks_without_content():
    with patch("conclave.infrastructure.openai.adapter.openai.OpenAI") as mock_openai:
        events = [
            make_mock_stream_event("response.output_text.delta", "Token"),
            make_mock_stream_event("response.other_event"),
            make_mock_stream_event("response.output_text.delta", "Ende"),
            make_mock_stream_event("response.completed"),
        ]
        mock_openai.return_value.responses.create.return_value = iter(events)

        adapter = OpenAIAdapter(api_key="test-key")
        conversation = make_conversation((MessageAuthorType.USER, "Hallo"))
        tokens = list(adapter.stream(conversation, make_participant()))

        assert tokens == ["Token", "Ende"]


def test_stream_ignores_empty_choices():
    with patch("conclave.infrastructure.openai.adapter.openai.OpenAI") as mock_openai:
        events = [
            make_mock_stream_event("response.output_text.delta", "OK"),
            make_mock_stream_event("response.completed"),
        ]
        mock_openai.return_value.responses.create.return_value = iter(events)

        adapter = OpenAIAdapter(api_key="test-key")
        conversation = make_conversation((MessageAuthorType.USER, "Hallo"))
        tokens = list(adapter.stream(conversation, make_participant()))

        assert tokens == ["OK"]


def test_stream_passes_system_prompt():
    with patch("conclave.infrastructure.openai.adapter.openai.OpenAI") as mock_openai:
        mock_openai.return_value.responses.create.return_value = iter([
            make_mock_stream_event("response.completed"),
        ])

        adapter = OpenAIAdapter(api_key="test-key", system_prompt="Sei praezise.")
        conversation = make_conversation((MessageAuthorType.USER, "Hallo"))
        list(adapter.stream(conversation, make_participant()))

        call_kwargs = mock_openai.return_value.responses.create.call_args.kwargs
        assert call_kwargs["instructions"] == "Sei praezise."
        assert call_kwargs["stream"] is True


def test_stream_forwards_model_and_max_tokens():
    with patch("conclave.infrastructure.openai.adapter.openai.OpenAI") as mock_openai:
        mock_openai.return_value.responses.create.return_value = iter([
            make_mock_stream_event("response.completed"),
        ])

        adapter = OpenAIAdapter(api_key="test-key", model="gpt-4o-mini", max_tokens=256)
        conversation = make_conversation((MessageAuthorType.USER, "Hallo"))
        list(adapter.stream(conversation, make_participant()))

        call_kwargs = mock_openai.return_value.responses.create.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4o-mini"
        assert call_kwargs["stream"] is True
