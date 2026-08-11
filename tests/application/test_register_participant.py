import pytest

from conclave.domain.errors import (
    ParticipantNotRegistered,
    ParticipantAlreadyRegistered,
)
from conclave.domain.participant import ParticipantType
from conclave.domain.errors import ConversationNotFound


def test_register_participant_returns_updated_conversation(service):
    conversation = service.create_conversation()

    updated = service.register_participant(
        conversation_id=conversation.id,
        participant_id="assistant",
        participant_type=ParticipantType.MODEL,
        name="GPT-5",
    )

    assert updated.id == conversation.id
    assert len(updated.participants) == 1
    assert updated.participants[0].id == "assistant"
    assert updated.participants[0].name == "GPT-5"
    assert updated.participants[0].participant_type == ParticipantType.MODEL


def test_cannot_register_participant_for_unknown_conversation(service):
    with pytest.raises(ConversationNotFound):
        service.register_participant(
            conversation_id="unknown-conversation",
            participant_id="assistant",
            participant_type=ParticipantType.MODEL,
            name="GPT-5",
        )


def test_cannot_register_duplicate_participant_id_for_same_conversation(service):
    conversation = service.create_conversation()

    service.register_participant(
        conversation_id=conversation.id,
        participant_id="assistant",
        participant_type=ParticipantType.MODEL,
        name="GPT-5",
    )

    with pytest.raises(ParticipantAlreadyRegistered):
        service.register_participant(
            conversation_id=conversation.id,
            participant_id="assistant",
            participant_type=ParticipantType.MODEL,
            name="GPT-5 duplicate",
        )


def test_register_two_participants_both_are_persisted(service):
    conversation = service.create_conversation()

    service.register_participant(
        conversation_id=conversation.id,
        participant_id="assistant-1",
        participant_type=ParticipantType.MODEL,
        name="Model A",
    )
    service.register_participant(
        conversation_id=conversation.id,
        participant_id="assistant-2",
        participant_type=ParticipantType.MODEL,
        name="Model B",
    )

    loaded = service.load_conversation(conversation.id)

    assert len(loaded.participants) == 2
    participant_ids = [p.id for p in loaded.participants]
    assert "assistant-1" in participant_ids
    assert "assistant-2" in participant_ids


def test_register_participant_for_existing_conversation(service):
    conversation = service.create_conversation()

    updated = service.register_participant(
        conversation_id=conversation.id,
        participant_id="assistant-1",
        participant_type=ParticipantType.MODEL,
        name="Model A",
    )
    loaded = service.load_conversation(conversation.id)

    assert updated.id == conversation.id
    assert len(updated.participants) == 1

    returned_participant = updated.participants[0]
    assert returned_participant.id == "assistant-1"
    assert returned_participant.conversation_id == conversation.id
    assert returned_participant.participant_type == ParticipantType.MODEL
    assert returned_participant.name == "Model A"
    assert returned_participant.created_at is not None

    assert loaded.id == conversation.id
    assert len(loaded.participants) == 1

    persisted_participant = loaded.participants[0]
    assert persisted_participant.id == "assistant-1"
    assert persisted_participant.conversation_id == conversation.id
    assert persisted_participant.participant_type == ParticipantType.MODEL
    assert persisted_participant.name == "Model A"
    assert persisted_participant.created_at is not None


def test_delete_participant_removes_participant(service):
    conversation = service.create_conversation()
    service.register_participant(
        conversation_id=conversation.id,
        participant_id="assistant-1",
        participant_type=ParticipantType.MODEL,
        name="Model A",
    )

    service.delete_participant(conversation.id, "assistant-1")
    loaded = service.load_conversation(conversation.id)

    assert loaded.participants == []


def test_delete_unknown_participant_raises(service):
    conversation = service.create_conversation()

    with pytest.raises(ParticipantNotRegistered):
        service.delete_participant(conversation.id, "missing")
