import json

from conclave.domain.context_report import ContextReportRecord
from conclave.infrastructure.sqlite.context_report_repository import (
    SQLiteContextReportRepository,
)


class PostgresContextReportRepository:
    def __init__(self, connection) -> None:
        self._connection = connection

    def save(self, record: ContextReportRecord) -> None:
        with self._connection.cursor() as cur:
            cur.execute(
                "INSERT INTO context_reports (id, conversation_id, participant_id, message_id, run_id, created_at, report_json) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    record.id,
                    record.conversation_id,
                    record.participant_id,
                    record.message_id,
                    record.run_id,
                    record.created_at,
                    json.dumps(record.payload(), ensure_ascii=False),
                ),
            )

    def link_message(self, record_id: str, message_id: str) -> None:
        with self._connection.cursor() as cur:
            cur.execute(
                "UPDATE context_reports SET message_id = %s WHERE id = %s",
                (message_id, record_id),
            )

    def get_by_message(self, message_id: str) -> ContextReportRecord | None:
        with self._connection.cursor() as cur:
            cur.execute(
                "SELECT id, conversation_id, participant_id, message_id, run_id, created_at, report_json "
                "FROM context_reports WHERE message_id = %s "
                "ORDER BY created_at DESC, id LIMIT 1",
                (message_id,),
            )
            row = cur.fetchone()
        return SQLiteContextReportRepository._row_to_record(row) if row else None

    def list_by_conversation(self, conversation_id: str) -> list[ContextReportRecord]:
        with self._connection.cursor() as cur:
            cur.execute(
                "SELECT id, conversation_id, participant_id, message_id, run_id, created_at, report_json "
                "FROM context_reports WHERE conversation_id = %s ORDER BY created_at, id",
                (conversation_id,),
            )
            rows = cur.fetchall()
        return [SQLiteContextReportRepository._row_to_record(row) for row in rows]
