# src/conclave/domain/audit.py

from dataclasses import dataclass
from datetime import datetime


@dataclass
class AuditEntry:
    """Laufprotokoll-Eintrag fuer Provider-Aufrufe."""

    id: str
    timestamp: datetime
    operation: str              # "invoke_participant", "stream_participant", etc.
    conversation_id: str
    participant_id: str
    provider: str               # "anthropic", "openai"
    model: str
    success: bool
    error_message: str | None = None
    user_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
