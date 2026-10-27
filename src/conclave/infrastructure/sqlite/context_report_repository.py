import json
from datetime import datetime

from conclave.domain.context_report import ContextReport, ContextReportRecord


class SQLiteContextReportRepository:
    def __init__(self, connection, *, autocommit: bool = False):
        self._connection = connection
        self._autocommit = autocommit

    def _commit_if_needed(self) -> None:
        if self._autocommit:
            self._connection.commit()

    def save(self, record: ContextReportRecord) -> None:
        self._connection.execute(
            "INSERT INTO context_reports (id, conversation_id, participant_id, message_id, run_id, created_at, report_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                record.id,
                record.conversation_id,
                record.participant_id,
                record.message_id,
                record.run_id,
                record.created_at.isoformat(),
                json.dumps(record.payload(), ensure_ascii=False),
            ),
        )
        self._commit_if_needed()

    def link_message(self, record_id: str, message_id: str) -> None:
        self._connection.execute(
            "UPDATE context_reports SET message_id = ? WHERE id = ?",
            (message_id, record_id),
        )
        self._commit_if_needed()

    def get_by_message(self, message_id: str) -> ContextReportRecord | None:
        row = self._connection.execute(
            "SELECT id, conversation_id, participant_id, message_id, run_id, created_at, report_json "
            "FROM context_reports WHERE message_id = ? "
            "ORDER BY created_at DESC, id LIMIT 1",
            (message_id,),
        ).fetchone()
        return self._row_to_record(row) if row else None

    def list_by_conversation(self, conversation_id: str) -> list[ContextReportRecord]:
        rows = self._connection.execute(
            "SELECT id, conversation_id, participant_id, message_id, run_id, created_at, report_json "
            "FROM context_reports WHERE conversation_id = ? ORDER BY created_at, id",
            (conversation_id,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    @staticmethod
    def _row_to_record(row) -> ContextReportRecord:
        payload = json.loads(row[6]) if row[6] else {}
        usage = payload.get("usage") or {}
        return ContextReportRecord(
            id=row[0],
            conversation_id=row[1],
            participant_id=row[2],
            message_id=row[3],
            run_id=row[4],
            created_at=row[5] if isinstance(row[5], datetime) else datetime.fromisoformat(row[5]),
            report=ContextReport.from_dict(payload.get("report") or {}),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )
