# tests/application/test_invoke_participant.py

import pytest

from conclave.application.ports import ModelAdapter
from conclave.domain.conversation import Conversation
from conclave.domain.participant import Participant, ParticipantType
from conclave.domain.message import MessageAuthorType


class FakeModelAdapter:
    """Gibt immer eine feste Antwort zurück – kein echter API-Call."""
    provider = "test"

    def __init__(self, response: str):
        self._response = response
        self.calls: list[Conversation] = []

    def complete(self, conversation: Conversation, participant: Participant) -> str:
        self.calls.append(conversation)
        return self._response


def test_invoke_participant_returns_updated_conversation(service):
    conversation = service.create_conversation()
    service.register_participant(
        conversation_id=conversation.id,
        participant_id="model-a",
        participant_type=ParticipantType.MODEL,
        name="Model A",
    )
    service.add_user_message(conversation.id, "Hallo!")

    adapter = FakeModelAdapter("Antwort von Model A")
    updated = service.invoke_participant(
        conversation_id=conversation.id,
        participant_id="model-a",
        adapter=adapter,
    )

    assert len(updated.messages) == 2
    model_message = updated.messages[1]
    assert model_message.author_type == MessageAuthorType.MODEL
    assert model_message.author_id == "model-a"
    assert model_message.content == "Antwort von Model A"


def test_invoke_participant_passes_full_conversation_to_adapter(service):
    conversation = service.create_conversation()
    service.register_participant(
        conversation_id=conversation.id,
        participant_id="model-a",
        participant_type=ParticipantType.MODEL,
        name="Model A",
    )
    service.add_user_message(conversation.id, "Erste Nachricht")
    service.add_user_message(conversation.id, "Zweite Nachricht")

    adapter = FakeModelAdapter("ok")
    service.invoke_participant(
        conversation_id=conversation.id,
        participant_id="model-a",
        adapter=adapter,
    )

    assert len(adapter.calls) == 1
    passed_conversation = adapter.calls[0]
    assert len(passed_conversation.messages) == 2


def test_invoke_participant_persists_model_message(service):
    conversation = service.create_conversation()
    service.register_participant(
        conversation_id=conversation.id,
        participant_id="model-a",
        participant_type=ParticipantType.MODEL,
        name="Model A",
    )
    service.add_user_message(conversation.id, "Hallo!")

    adapter = FakeModelAdapter("Persistierte Antwort")
    service.invoke_participant(
        conversation_id=conversation.id,
        participant_id="model-a",
        adapter=adapter,
    )

    loaded = service.load_conversation(conversation.id)
    assert len(loaded.messages) == 2
    assert loaded.messages[1].content == "Persistierte Antwort"
    assert loaded.messages[1].author_id == "model-a"


def test_invoke_participant_raises_for_unknown_participant(service):
    from conclave.domain.errors import ParticipantNotRegistered

    conversation = service.create_conversation()
    adapter = FakeModelAdapter("x")

    with pytest.raises(ParticipantNotRegistered):
        service.invoke_participant(
            conversation_id=conversation.id,
            participant_id="unbekannt",
            adapter=adapter,
        )


def test_invoke_participant_raises_for_empty_conversation(service):
    from conclave.domain.errors import EmptyConversation

    conversation = service.create_conversation()
    service.register_participant(
        conversation_id=conversation.id,
        participant_id="model-a",
        participant_type=ParticipantType.MODEL,
        name="Model A",
    )
    adapter = FakeModelAdapter("x")

    with pytest.raises(EmptyConversation):
        service.invoke_participant(
            conversation_id=conversation.id,
            participant_id="model-a",
            adapter=adapter,
        )

    assert adapter.calls == []


def test_fake_adapter_satisfies_protocol():
    adapter = FakeModelAdapter("test")
    assert isinstance(adapter, ModelAdapter)


def test_invoke_participant_uses_registry_when_no_adapter_passed(service):
    from conclave.application.adapter_registry import AdapterRegistry

    conversation = service.create_conversation()
    service.register_participant(
        conversation_id=conversation.id,
        participant_id="model-a",
        participant_type=ParticipantType.MODEL,
        name="Model A",
    )
    service.add_user_message(conversation.id, "Hallo!")

    registry = AdapterRegistry()
    registry.register("model-a", FakeModelAdapter("Antwort aus Registry"))
    service.set_adapter_registry(registry)

    updated = service.invoke_participant(
        conversation_id=conversation.id,
        participant_id="model-a",
    )

    assert updated.messages[1].content == "Antwort aus Registry"


def test_invoke_participant_explicit_adapter_takes_precedence_over_registry(service):
    from conclave.application.adapter_registry import AdapterRegistry

    conversation = service.create_conversation()
    service.register_participant(
        conversation_id=conversation.id,
        participant_id="model-a",
        participant_type=ParticipantType.MODEL,
        name="Model A",
    )
    service.add_user_message(conversation.id, "Hallo!")

    registry = AdapterRegistry()
    registry.register("model-a", FakeModelAdapter("Aus Registry"))
    service.set_adapter_registry(registry)

    explicit_adapter = FakeModelAdapter("Explizit übergeben")
    updated = service.invoke_participant(
        conversation_id=conversation.id,
        participant_id="model-a",
        adapter=explicit_adapter,
    )

    assert updated.messages[1].content == "Explizit übergeben"


def test_invoke_participant_raises_when_no_adapter_and_no_registry(service):
    from conclave.domain.errors import AdapterNotFound

    conversation = service.create_conversation()
    service.register_participant(
        conversation_id=conversation.id,
        participant_id="model-a",
        participant_type=ParticipantType.MODEL,
        name="Model A",
    )

    with pytest.raises(AdapterNotFound):
        service.invoke_participant(
            conversation_id=conversation.id,
            participant_id="model-a",
        )
