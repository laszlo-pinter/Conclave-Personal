from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class UsageRecord:
    """Token- und Provider-Metadaten eines Agent-Aufrufs."""

    provider: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None

    @property
    def total_tokens(self) -> int:
        return (self.input_tokens or 0) + (self.output_tokens or 0)


@dataclass(frozen=True)
class Run:
    """Ein einzelner Arbeitslauf in Conclave Personal."""

    id: str
    conversation_id: str
    kind: str
    participants: list[str]
    started_at: datetime
    finished_at: datetime | None
    status: str
    error: str | None = None
    usage: UsageRecord | None = None
