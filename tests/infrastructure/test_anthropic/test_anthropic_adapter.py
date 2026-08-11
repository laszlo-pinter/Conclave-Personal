# tests/infrastructure/anthropic/test_anthropic_adapter.py

from unittest.mock import MagicMock, patch
import uuid

import pytest
pytest.importorskip("anthropic")

from conclave.domain.conversation import Conversation
from conclave.domain.message import Message, MessageAuthorType
from conclave.domain.participant import Participant, ParticipantType
from conclave.infrastructure.anthropic.adapter import AnthropicAdapter
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


def test_anthropic_adapter_satisfies_protocol():
    with patch("conclave.infrastructure.anthropic.adapter.anthropic.Anthropic"):
        adapter = AnthropicAdapter(api_key="test-key")
        assert isinstance(adapter, ModelAdapter)


def test_complete_returns_model_response():
    with patch("conclave.infrastructure.anthropic.adapter.anthropic.Anthropic") as mock_anthropic:
        mock_client = mock_anthropic.return_value
        mock_client.messages.create.return_value = make_mock_response("Hallo vom Modell")

        adapter = AnthropicAdapter(api_key="test-key")
        conversation = make_conversation(
            (MessageAuthorType.USER, "Hallo!")
        )
        result = adapter.complete(conversation, make_participant())

        assert result == "Hallo vom Modell"


def test_messages_are_mapped_to_anthropic_format():
    with patch("conclave.infrastructure.anthropic.adapter.anthropic.Anthropic") as mock_anthropic:
        mock_client = mock_anthropic.return_value
        mock_client.messages.create.return_value = make_mock_response("ok")

        adapter = AnthropicAdapter(api_key="test-key")
        conversation = make_conversation(
            (MessageAuthorType.USER, "Erste Frage"),
            (MessageAuthorType.MODEL, "Erste Antwort"),
            (MessageAuthorType.USER, "Zweite Frage"),
        )
        adapter.complete(conversation, make_participant())

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["messages"] == [
            {"role": "user", "content": "Erste Frage"},
            {"role": "assistant", "content": "Erste Antwort"},
            {"role": "user", "content": "Zweite Frage"},
        ]


def test_system_prompt_is_passed_when_set():
    with patch("conclave.infrastructure.anthropic.adapter.anthropic.Anthropic") as mock_anthropic:
        mock_client = mock_anthropic.return_value
        mock_client.messages.create.return_value = make_mock_response("ok")

        adapter = AnthropicAdapter(api_key="test-key", system_prompt="Du bist ein Assistent.")
        conversation = make_conversation((MessageAuthorType.USER, "Hallo"))
        adapter.complete(conversation, make_participant())

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["system"] == "Du bist ein Assistent."


def test_no_system_prompt_by_default():
    with patch("conclave.infrastructure.anthropic.adapter.anthropic.Anthropic") as mock_anthropic:
        mock_client = mock_anthropic.return_value
        mock_client.messages.create.return_value = make_mock_response("ok")

        adapter = AnthropicAdapter(api_key="test-key")
        conversation = make_conversation((MessageAuthorType.USER, "Hallo"))
        adapter.complete(conversation, make_participant())

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "system" not in call_kwargs


def test_model_and_max_tokens_are_forwarded():
    with patch("conclave.infrastructure.anthropic.adapter.anthropic.Anthropic") as mock_anthropic:
        mock_client = mock_anthropic.return_value
        mock_client.messages.create.return_value = make_mock_response("ok")

        adapter = AnthropicAdapter(
            api_key="test-key",
            model="claude-opus-4-6",
            max_tokens=1024,
        )
        conversation = make_conversation((MessageAuthorType.USER, "Hallo"))
        adapter.complete(conversation, make_participant())

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-opus-4-6"
        assert call_kwargs["max_tokens"] == 1024


# ── Streaming ──────────────────────────────────────────────────────────────

def test_anthropic_adapter_satisfies_streaming_protocol():
    from conclave.application.ports import StreamingModelAdapter
    with patch("conclave.infrastructure.anthropic.adapter.anthropic.Anthropic"):
        adapter = AnthropicAdapter(api_key="test-key")
        assert isinstance(adapter, StreamingModelAdapter)


def _make_stream_mock(events):
    """Baut einen Mock der als Context-Manager iterierbar ist UND get_final_message() hat."""
    stream = MagicMock()
    stream.__iter__ = MagicMock(return_value=iter(events))
    stream.get_final_message.return_value = MagicMock(
        usage=MagicMock(input_tokens=10, output_tokens=5)
    )
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=stream)
    cm.__exit__ = MagicMock(return_value=False)
    return cm


def test_stream_yields_tokens():
    with patch("conclave.infrastructure.anthropic.adapter.anthropic.Anthropic") as mock_anthropic:
        mock_event_1 = MagicMock(type="content_block_delta", delta=MagicMock(type="text_delta", text="Hal"))
        mock_event_2 = MagicMock(type="content_block_delta", delta=MagicMock(type="text_delta", text="lo"))
        mock_event_3 = MagicMock(type="message_stop")

        mock_anthropic.return_value.messages.stream.return_value = _make_stream_mock(
            [mock_event_1, mock_event_2, mock_event_3]
        )

        adapter = AnthropicAdapter(api_key="test-key")
        conversation = make_conversation((MessageAuthorType.USER, "Hallo"))
        tokens = list(adapter.stream(conversation, make_participant()))

        assert tokens == ["Hal", "lo"]


def test_stream_ignores_non_text_delta_events():
    with patch("conclave.infrastructure.anthropic.adapter.anthropic.Anthropic") as mock_anthropic:
        mock_text = MagicMock(type="content_block_delta", delta=MagicMock(type="text_delta", text="Token"))
        mock_other = MagicMock(type="content_block_delta", delta=MagicMock(type="input_json_delta", text="ignored"))
        mock_stop = MagicMock(type="message_stop")

        mock_anthropic.return_value.messages.stream.return_value = _make_stream_mock(
            [mock_text, mock_other, mock_stop]
        )

        adapter = AnthropicAdapter(api_key="test-key")
        conversation = make_conversation((MessageAuthorType.USER, "Hallo"))
        tokens = list(adapter.stream(conversation, make_participant()))

        assert tokens == ["Token"]


def test_stream_passes_system_prompt_when_set():
    with patch("conclave.infrastructure.anthropic.adapter.anthropic.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.messages.stream.return_value = _make_stream_mock([])

        adapter = AnthropicAdapter(api_key="test-key", system_prompt="Sei präzise.")
        conversation = make_conversation((MessageAuthorType.USER, "Hallo"))
        list(adapter.stream(conversation, make_participant()))

        call_kwargs = mock_anthropic.return_value.messages.stream.call_args.kwargs
        assert call_kwargs["system"] == "Sei präzise."
