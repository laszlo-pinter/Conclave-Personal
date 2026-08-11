# src/conclave/infrastructure/sqlite/audit_repository.py

from datetime import datetime

from conclave.domain.audit import AuditEntry


class SQLiteAuditRepository:
    def __init__(self, connection):
        self._connection = connection

    def save(self, entry: AuditEntry) -> None:
        self._connection.execute(
            """
            INSERT INTO audit_log (
                id, timestamp, operation, conversation_id, participant_id,
                provider, model, success, error_message, user_id,
                input_tokens, output_tokens
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.id,
                entry.timestamp.isoformat(),
                entry.operation,
                entry.conversation_id,
                entry.participant_id,
                entry.provider,
                entry.model,
                1 if entry.success else 0,
                entry.error_message,
                entry.user_id,
                entry.input_tokens,
                entry.output_tokens,
            ),
        )

    def list_by_conversation(self, conversation_id: str) -> list[AuditEntry]:
        rows = self._connection.execute(
            """
            SELECT id, timestamp, operation, conversation_id, participant_id,
                   provider, model, success, error_message, user_id,
                   input_tokens, output_tokens
            FROM audit_log WHERE conversation_id = ? ORDER BY timestamp
            """,
            (conversation_id,),
        ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def list_by_date_range(self, start: datetime, end: datetime) -> list[AuditEntry]:
        rows = self._connection.execute(
            """
            SELECT id, timestamp, operation, conversation_id, participant_id,
                   provider, model, success, error_message, user_id,
                   input_tokens, output_tokens
            FROM audit_log WHERE timestamp >= ? AND timestamp < ? ORDER BY timestamp
            """,
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def get_usage_summary(self) -> list[dict]:
        """Token-Verbrauch aggregiert pro Provider + Model."""
        rows = self._connection.execute(
            """
            SELECT provider, model,
                   COUNT(*) as calls,
                   COALESCE(SUM(input_tokens), 0) as total_input,
                   COALESCE(SUM(output_tokens), 0) as total_output
            FROM audit_log
            WHERE success = 1
            GROUP BY provider, model
            ORDER BY total_input + total_output DESC
            """,
        ).fetchall()
        return [
            {
                "provider": r[0], "model": r[1], "calls": r[2],
                "input_tokens": r[3], "output_tokens": r[4],
                "total_tokens": r[3] + r[4],
            }
            for r in rows
        ]

    def get_usage_by_conversation(self) -> list[dict]:
        """Token-Verbrauch aggregiert pro Conversation + Provider."""
        rows = self._connection.execute(
            """
            SELECT a.conversation_id, c.topic, c.status,
                   a.provider, a.model,
                   COUNT(*) as calls,
                   COALESCE(SUM(a.input_tokens), 0) as total_input,
                   COALESCE(SUM(a.output_tokens), 0) as total_output
            FROM audit_log a
            LEFT JOIN conversations c ON a.conversation_id = c.id
            WHERE a.success = 1
            GROUP BY a.conversation_id, c.topic, c.status, a.provider, a.model
            ORDER BY a.conversation_id, COALESCE(SUM(a.input_tokens), 0) + COALESCE(SUM(a.output_tokens), 0) DESC
            """,
        ).fetchall()
        return [
            {"conversation_id": r[0], "topic": r[1] or "", "status": r[2] or "",
             "provider": r[3], "model": r[4], "calls": r[5],
             "input_tokens": r[6], "output_tokens": r[7],
             "total_tokens": r[6] + r[7]}
            for r in rows
        ]

    @staticmethod
    def _row_to_entry(row) -> AuditEntry:
        return AuditEntry(
            id=row[0],
            timestamp=datetime.fromisoformat(row[1]),
            operation=row[2],
            conversation_id=row[3],
            participant_id=row[4],
            provider=row[5],
            model=row[6],
            success=bool(row[7]),
            error_message=row[8],
            user_id=row[9],
            input_tokens=row[10],
            output_tokens=row[11],
        )
