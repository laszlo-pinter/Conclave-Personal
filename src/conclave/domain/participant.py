from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


class ParticipantType(str, Enum):
    """Typ eines Conversation-Teilnehmers."""
    USER = "user"
    MODEL = "model"


@dataclass(frozen=True)
class Participant:
    """Teilnehmer einer Conversation (User oder Model-Agent). Immutable."""
    id: str
    conversation_id: str
    participant_type: ParticipantType
    name: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if self.name.strip() == "":
            raise ValueError("name must not be empty")
