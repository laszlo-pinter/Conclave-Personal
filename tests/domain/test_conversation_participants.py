import pytest

from conclave.domain.conversation import Conversation
from conclave.domain.errors import ParticipantConversationMismatch
from conclave.domain.participant import Participant, ParticipantType


def test_conversation_rejects_participant_from_different_conversation():
    first_conversation = Conversation.create()
    second_conversation = Conversation.create()

    participant = Participant(
        id="assistant",
        conversation_id=second_conversation.id,
        participant_type=ParticipantType.MODEL,
        name="GPT-5",
    )

    with pytest.raises(ParticipantConversationMismatch):
        first_conversation.add_participant(participant)