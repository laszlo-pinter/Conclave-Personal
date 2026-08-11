import uuid

import pytest

from conclave.domain.participant import Participant, ParticipantType


def test_create_participant_creates_participant_with_identity():
    conversation_id = str(uuid.uuid4())

    participant = Participant(
        id=str(uuid.uuid4()),
        conversation_id=conversation_id,
        participant_type=ParticipantType.USER,
        name="Alice",
    )

    assert participant.id
    assert participant.conversation_id == conversation_id


def test_participant_belongs_to_conversation():
    conversation_id = str(uuid.uuid4())

    participant = Participant(
        id=str(uuid.uuid4()),
        conversation_id=conversation_id,
        participant_type=ParticipantType.USER,
        name="Alice",
    )

    assert participant.conversation_id == conversation_id


def test_participant_has_type_and_name():
    participant = Participant(
        id=str(uuid.uuid4()),
        conversation_id=str(uuid.uuid4()),
        participant_type=ParticipantType.MODEL,
        name="GPT-Adapter",
    )

    assert participant.participant_type == ParticipantType.MODEL
    assert participant.name == "GPT-Adapter"
    assert participant.created_at is not None


def test_participant_type_supports_user_and_model():
    assert ParticipantType.USER.value == "user"
    assert ParticipantType.MODEL.value == "model"


def test_participant_name_must_not_be_empty():
    with pytest.raises(ValueError, match="name must not be empty"):
        Participant(
            id=str(uuid.uuid4()),
            conversation_id=str(uuid.uuid4()),
            participant_type=ParticipantType.USER,
            name="   ",
        )
