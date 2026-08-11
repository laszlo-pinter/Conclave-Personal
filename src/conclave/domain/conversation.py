from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from conclave.domain.message import Message, MessageAuthorType
from conclave.domain.errors import (
    FloorNotGranted,
    ParticipantAlreadyRegistered,
    ParticipantConversationMismatch,
    ParticipantNotRegistered,
)
from conclave.domain.participant import Participant

@dataclass
class Conversation:
    """Zentrale Entitaet: Eine host-gesteuerte Multi-Model-Konversation.

    Verwaltet Participants, Messages und Floor (Rederecht).
    Der Host entscheidet wann welcher Participant antwortet.
    """
    id: str
    status: str = "active"
    topic: str = ""
    floor: str | None = None          # participant_id mit Rederecht, None = niemand
    rules: str = ""                   # Chat-Regeln fuer Agenten (System-Instruktionen)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    messages: list[Message] = field(default_factory=list)
    participants: list[Participant] = field(default_factory=list)

    def add_message(self, message: Message) -> None:
        """Fuegt eine Message zur Conversation hinzu."""
        self.messages.append(message)

    def add_participant(self, participant):
        """Registriert einen Participant. Wirft bei Duplikat oder falscher Conversation."""
        if participant.conversation_id != self.id:
            raise ParticipantConversationMismatch(
            participant_conversation_id=participant.conversation_id,
            conversation_id=self.id,
        )

        if any(existing.id == participant.id for existing in self.participants):
            raise ParticipantAlreadyRegistered(
                participant_id=participant.id,
                conversation_id=self.id,
            )

        self.participants.append(participant)

    def grant_floor(self, participant_id: str) -> None:
        """Erteilt einem Participant das Rederecht."""
        if not any(p.id == participant_id for p in self.participants):
            raise ParticipantNotRegistered(
                participant_id=participant_id,
                conversation_id=self.id,
            )
        self.floor = participant_id

    def revoke_floor(self) -> None:
        """Entzieht das Rederecht."""
        self.floor = None

    def assert_has_floor(self, participant_id: str) -> None:
        """Wirft FloorNotGranted wenn der Participant kein Rederecht hat."""
        if self.floor != participant_id:
            raise FloorNotGranted(participant_id, self.floor)

    @staticmethod
    def create(topic: str = "") -> "Conversation":
        return Conversation(
            id=str(uuid4()),
            topic=topic,
        )

    def add_user_message(self, content: str) -> Message:
        """Erzeugt und fuegt eine User-Message hinzu."""
        message = Message.create_user_message(
            conversation_id=self.id,
            content=content,
            sequence=len(self.messages) + 1,
        )
        self.messages.append(message)
        return message
    
    def add_model_message(self, participant_id: str, content: str) -> Message:
        """Erzeugt und fuegt eine Model-Message hinzu. Wirft bei unbekanntem Participant."""
        participant = next(
            (existing for existing in self.participants if existing.id == participant_id),
            None,
        )
        if participant is None:
            raise ParticipantNotRegistered(
                participant_id=participant_id,
                conversation_id=self.id,
            )

        message = Message.create_model_message(
            conversation_id=self.id,
            author_id=participant.id,
            content=content,
            sequence=len(self.messages) + 1,
        )
        self.messages.append(message)
        return message