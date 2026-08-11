# tests/application/test_participant_service.py

import pytest

from conclave.application.participant_service import ParticipantService
from conclave.domain.errors import ConversationNotFound, ParticipantAlreadyRegistered
from conclave.domain.participant import ParticipantType


def test_register_participant_returns_updated_conversation(service):
    conversation = service.create_conversation()

    participant_service = ParticipantService(
        service._conversation_repository,
        service._participant_repository,
    )

    updated = participant_service.register_participant(
        conversation_id=conversation.id,
        participant_id="p1",
        participant_type=ParticipantType.MODEL,
        name="Model A",
    )

    assert updated.id == conversation.id
    assert len(updated.participants) == 1
    assert updated.participants[0].id == "p1"


def test_register_participant_raises_for_unknown_conversation(service):
    participant_service = ParticipantService(
        service._conversation_repository,
        service._participant_repository,
    )

    with pytest.raises(ConversationNotFound):
        participant_service.register_participant(
            conversation_id="unknown",
            participant_id="p1",
            participant_type=ParticipantType.MODEL,
            name="Model A",
        )


def test_register_duplicate_participant_raises(service):
    conversation = service.create_conversation()
    participant_service = ParticipantService(
        service._conversation_repository,
        service._participant_repository,
    )

    participant_service.register_participant(
        conversation_id=conversation.id,
        participant_id="p1",
        participant_type=ParticipantType.MODEL,
        name="Model A",
    )

    with pytest.raises(ParticipantAlreadyRegistered):
        participant_service.register_participant(
            conversation_id=conversation.id,
            participant_id="p1",
            participant_type=ParticipantType.MODEL,
            name="Model A duplicate",
        )
