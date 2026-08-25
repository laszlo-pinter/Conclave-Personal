from dataclasses import dataclass, field
from datetime import UTC, datetime
import uuid


@dataclass
class ToolEvent:
    """A deterministic backend event caused by a model tool directive."""

    id: str
    conversation_id: str
    participant_id: str
    tool: str
    status: str
    input_json: dict
    output_json: dict = field(default_factory=dict)
    error: str | None = None
    message_id: str | None = None
    run_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @staticmethod
    def create(
        *,
        conversation_id: str,
        participant_id: str,
        tool: str,
        status: str,
        input_json: dict,
        output_json: dict | None = None,
        error: str | None = None,
        message_id: str | None = None,
        run_id: str | None = None,
    ) -> "ToolEvent":
        return ToolEvent(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            participant_id=participant_id,
            tool=tool,
            status=status,
            input_json=input_json,
            output_json=output_json or {},
            error=error,
            message_id=message_id,
            run_id=run_id,
        )
