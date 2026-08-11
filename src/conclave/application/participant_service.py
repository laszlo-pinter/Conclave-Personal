# src/conclave/application/participant_service.py

from conclave.application.ports import ConversationRepository, ParticipantRepository
from conclave.domain.conversation import Conversation
from conclave.domain.errors import ConversationNotFound
from conclave.domain.participant import Participant, ParticipantType


class ParticipantService:
    def __init__(
        self,
        conversation_repository: ConversationRepository,
        participant_repository: ParticipantRepository,
    ):
        self._conversation_repository = conversation_repository
        self._participant_repository = participant_repository

    def register_participant(
        self,
        conversation_id: str,
        participant_id: str,
        participant_type: ParticipantType,
        name: str,
    ) -> Conversation:
        conversation = self._conversation_repository.load(conversation_id)

        if conversation is None:
            raise ConversationNotFound(conversation_id)

        # Bereits registrierte Participants laden, damit add_participant
        # Duplikate erkennen kann
        conversation.participants = self._participant_repository.list_by_conversation_id(
            conversation_id
        )

        participant = Participant(
            id=participant_id,
            conversation_id=conversation_id,
            participant_type=participant_type,
            name=name,
        )

        conversation.add_participant(participant)        # wirft ParticipantAlreadyRegistered bei Duplikat

        self._conversation_repository.save(conversation)
        self._participant_repository.save(participant)  # explizite Persistenz

        return conversation

    def delete_participant(self, conversation_id: str, participant_id: str) -> Conversation:
        conversation = self._conversation_repository.load(conversation_id)
        if conversation is None:
            raise ConversationNotFound(conversation_id)

        conversation.participants = self._participant_repository.list_by_conversation_id(
            conversation_id
        )
        if not any(p.id == participant_id for p in conversation.participants):
            from conclave.domain.errors import ParticipantNotRegistered
            raise ParticipantNotRegistered(participant_id, conversation_id)

        conversation.participants = [
            p for p in conversation.participants if p.id != participant_id
        ]
        if conversation.floor == participant_id:
            conversation.revoke_floor()
        self._participant_repository.delete(conversation_id, participant_id)
        self._conversation_repository.save(conversation)
        return conversation
