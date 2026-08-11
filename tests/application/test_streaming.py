# tests/application/test_streaming.py

from collections.abc import Iterator

import pytest

from conclave.application.ports import StreamingModelAdapter
from conclave.domain.conversation import Conversation
from conclave.domain.participant import Participant, ParticipantType


class FakeStreamingAdapter:
    """Gibt Tokens als Iterator zurück – kein echter API-Call."""
    provider = "test"

    def __init__(self, tokens: list[str]):
        self._tokens = tokens
        self.calls: list[int] = []  # message_count zum Zeitpunkt des Aufrufs

    def complete(self, conversation: Conversation, participant: Participant) -> str:
        return "".join(self._tokens)

    def stream(self, conversation: Conversation, participant: Participant) -> Iterator[str]:
        self.calls.append(len(conversation.messages))
        yield from self._tokens


# ── Protocol-Konformität ───────────────────────────────────────────────────

def test_fake_streaming_adapter_satisfies_protocol():
    adapter = FakeStreamingAdapter(["Hallo", " Welt"])
    assert isinstance(adapter, StreamingModelAdapter)


# ── stream_participant ─────────────────────────────────────────────────────

def test_stream_participant_yields_tokens(service):
    from conclave.application.adapter_registry import AdapterRegistry

    adapter = FakeStreamingAdapter(["Hallo", " ", "Welt"])
    registry = AdapterRegistry()
    registry.register("p1", adapter)
    service.set_adapter_registry(registry)

    conversation = service.create_conversation()
    service.register_participant(
        conversation_id=conversation.id,
        participant_id="p1",
        participant_type=ParticipantType.MODEL,
        name="Model A",
    )
    service.add_user_message(conversation.id, "Frage")

    tokens = list(service.stream_participant(conversation.id, "p1"))

    assert tokens == ["Hallo", " ", "Welt"]


def test_stream_participant_persists_complete_message_after_stream(service):
    from conclave.application.adapter_registry import AdapterRegistry

    adapter = FakeStreamingAdapter(["Teil1", " Teil2"])
    registry = AdapterRegistry()
    registry.register("p1", adapter)
    service.set_adapter_registry(registry)

    conversation = service.create_conversation()
    service.register_participant(
        conversation_id=conversation.id,
        participant_id="p1",
        participant_type=ParticipantType.MODEL,
        name="Model A",
    )
    service.add_user_message(conversation.id, "Frage")

    # Kompletten Stream konsumieren
    list(service.stream_participant(conversation.id, "p1"))

    loaded = service.load_conversation(conversation.id)
    assert len(loaded.messages) == 2
    assert loaded.messages[1].content == "Teil1 Teil2"
    assert loaded.messages[1].author_id == "p1"


def test_stream_participant_passes_snapshot_to_adapter(service):
    from conclave.application.adapter_registry import AdapterRegistry

    adapter = FakeStreamingAdapter(["ok"])
    registry = AdapterRegistry()
    registry.register("p1", adapter)
    service.set_adapter_registry(registry)

    conversation = service.create_conversation()
    service.register_participant(
        conversation_id=conversation.id,
        participant_id="p1",
        participant_type=ParticipantType.MODEL,
        name="Model A",
    )
    service.add_user_message(conversation.id, "Frage")

    list(service.stream_participant(conversation.id, "p1"))

    # Adapter wurde mit 1 Message aufgerufen (nur user-message, nicht eigene Antwort)
    assert adapter.calls[0] == 1


def test_stream_participant_raises_for_unknown_participant(service):
    from conclave.domain.errors import ParticipantNotRegistered

    conversation = service.create_conversation()

    with pytest.raises(ParticipantNotRegistered):
        list(service.stream_participant(conversation.id, "unbekannt"))


def test_stream_participant_raises_for_unknown_conversation(service):
    from conclave.domain.errors import ConversationNotFound

    with pytest.raises(ConversationNotFound):
        list(service.stream_participant("unbekannt", "p1"))


def test_stream_participant_raises_for_missing_adapter(service):
    from conclave.domain.errors import AdapterNotFound

    conversation = service.create_conversation()
    service.register_participant(
        conversation_id=conversation.id,
        participant_id="p1",
        participant_type=ParticipantType.MODEL,
        name="Model A",
    )

    with pytest.raises(AdapterNotFound):
        list(service.stream_participant(conversation.id, "p1"))


def test_stream_participant_adapter_without_stream_falls_back_to_complete(service):
    """Adapter mit nur complete() – stream_participant() soll trotzdem funktionieren."""
    from conclave.application.adapter_registry import AdapterRegistry

    class NonStreamingAdapter:
        def complete(self, conversation: Conversation, participant: Participant) -> str:
            return "Vollständige Antwort"

    registry = AdapterRegistry()
    registry.register("p1", NonStreamingAdapter())
    service.set_adapter_registry(registry)

    conversation = service.create_conversation()
    service.register_participant(
        conversation_id=conversation.id,
        participant_id="p1",
        participant_type=ParticipantType.MODEL,
        name="Model A",
    )
    service.add_user_message(conversation.id, "Frage")

    tokens = list(service.stream_participant(conversation.id, "p1"))

    assert tokens == ["Vollständige Antwort"]

    loaded = service.load_conversation(conversation.id)
    assert loaded.messages[1].content == "Vollständige Antwort"
