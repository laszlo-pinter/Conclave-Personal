from dataclasses import dataclass
from datetime import datetime, UTC
from enum import Enum
import uuid


class MessageAuthorType(str, Enum):
    """Unterscheidet User-Eingaben von Model-Antworten."""
    USER = "user"
    MODEL = "model"


@dataclass
class Message:
    """Einzelne Nachricht in einer Conversation.

    Sequence wird atomar von der DB vergeben (nicht im Speicher berechnet).
    author_id ist None fuer User-Messages, Participant-ID fuer Model-Messages.
    """
    id: str
    conversation_id: str
    author_type: MessageAuthorType
    author_id: str | None
    content: str
    sequence: int
    created_at: datetime

    @staticmethod
    def create_user_message(
        conversation_id: str,
        content: str,
        sequence: int,
    ) -> "Message":
        """Erzeugt eine User-Message mit neuer UUID."""
        return Message(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            author_type=MessageAuthorType.USER,
            author_id=None,
            content=content,
            sequence=sequence,
            created_at=datetime.now(UTC),
        )

    @staticmethod
    def create_model_message(
        conversation_id: str,
        author_id: str,
        content: str,
        sequence: int,
    ) -> "Message":
        """Erzeugt eine Model-Message mit author_id des antwortenden Participants."""
        return Message(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            author_type=MessageAuthorType.MODEL,
            author_id=author_id,
            content=content,
            sequence=sequence,
            created_at=datetime.now(UTC),
        )