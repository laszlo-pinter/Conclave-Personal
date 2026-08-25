import json
from datetime import datetime

from conclave.domain.tool_event import ToolEvent


class SQLiteToolEventRepository:
    def __init__(self, connection, *, autocommit: bool = False):
        self._connection = connection
        self._autocommit = autocommit

    def _commit_if_needed(self) -> None:
        if self._autocommit:
            self._connection.commit()

    def save(self, event: ToolEvent) -> None:
        self._connection.execute(
            """
            INSERT INTO tool_events (
                id, conversation_id, message_id, run_id, participant_id,
                tool, status, input_json, output_json, error, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.conversation_id,
                event.message_id,
                event.run_id,
                event.participant_id,
                event.tool,
                event.status,
                json.dumps(event.input_json, ensure_ascii=False),
                json.dumps(event.output_json, ensure_ascii=False),
                event.error,
                event.created_at.isoformat(),
            ),
        )
        self._commit_if_needed()

    def list_by_conversation(self, conversation_id: str) -> list[ToolEvent]:
        rows = self._connection.execute(
            """
            SELECT id, conversation_id, message_id, run_id, participant_id,
                   tool, status, input_json, output_json, error, created_at
            FROM tool_events
            WHERE conversation_id = ?
            ORDER BY created_at, id
            """,
            (conversation_id,),
        ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def list_by_message(self, message_id: str) -> list[ToolEvent]:
        rows = self._connection.execute(
            """
            SELECT id, conversation_id, message_id, run_id, participant_id,
                   tool, status, input_json, output_json, error, created_at
            FROM tool_events
            WHERE message_id = ?
            ORDER BY created_at, id
            """,
            (message_id,),
        ).fetchall()
        return [self._row_to_event(row) for row in rows]

    @staticmethod
    def _row_to_event(row) -> ToolEvent:
        return ToolEvent(
            id=row[0],
            conversation_id=row[1],
            message_id=row[2],
            run_id=row[3],
            participant_id=row[4],
            tool=row[5],
            status=row[6],
            input_json=json.loads(row[7]) if row[7] else {},
            output_json=json.loads(row[8]) if row[8] else {},
            error=row[9],
            created_at=datetime.fromisoformat(row[10]),
        )
