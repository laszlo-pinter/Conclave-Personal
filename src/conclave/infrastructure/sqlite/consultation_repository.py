import json
from datetime import datetime

from conclave.domain.consultation import QUEUED, RUNNING, Consultation, ConsultationDelivery


def _ts(value):
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def row_to_consultation(row) -> Consultation:
    return Consultation(
        id=row[0], source=row[1], source_ref=row[2], question=row[3],
        reviewers=tuple(json.loads(row[4])), channel=row[5], mode=row[6], context=row[7] or "",
        requested_by=row[8] or "", include_previous=bool(row[9]), status=row[10], error=row[11],
        conversation_id=row[12], created_at=_ts(row[13]), finished_at=_ts(row[14]),
    )


def row_to_delivery(row) -> ConsultationDelivery:
    return ConsultationDelivery(
        id=row[0], consultation_id=row[1], participant_id=row[2], message_id=row[3], marker=row[4],
        status=row[5], attempts=row[6], error=row[7], delivered_at=_ts(row[8]),
    )


class SQLiteConsultationRepository:
    def __init__(self, connection, *, autocommit: bool = False):
        self._connection = connection
        self._autocommit = autocommit

    def _commit_if_needed(self) -> None:
        if self._autocommit:
            self._connection.commit()

    def save(self, c: Consultation) -> None:
        self._connection.execute(
            """
            INSERT INTO consultations (
                id, source, source_ref, question, reviewers_json, channel, mode, context,
                requested_by, include_previous, status, error, conversation_id, created_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status          = excluded.status,
                error           = excluded.error,
                conversation_id = excluded.conversation_id,
                finished_at     = excluded.finished_at
            """,
            (c.id, c.source, c.source_ref, c.question, json.dumps(list(c.reviewers)), c.channel, c.mode,
             c.context, c.requested_by, int(c.include_previous), c.status, c.error, c.conversation_id,
             c.created_at.isoformat(), c.finished_at.isoformat() if c.finished_at else None),
        )
        self._commit_if_needed()

    def get(self, consultation_id: str) -> Consultation | None:
        row = self._connection.execute(
            "SELECT id, source, source_ref, question, reviewers_json, channel, mode, context, requested_by, "
            "include_previous, status, error, conversation_id, created_at, finished_at "
            "FROM consultations WHERE id = ?",
            (consultation_id,),
        ).fetchone()
        return row_to_consultation(row) if row else None

    def list_by_source_ref(self, source: str, source_ref: str) -> list[Consultation]:
        rows = self._connection.execute(
            "SELECT id, source, source_ref, question, reviewers_json, channel, mode, context, requested_by, "
            "include_previous, status, error, conversation_id, created_at, finished_at "
            "FROM consultations WHERE source = ? AND source_ref = ? ORDER BY created_at DESC, id",
            (source, source_ref),
        ).fetchall()
        return [row_to_consultation(r) for r in rows]

    def list_by_status(self, status: str) -> list[Consultation]:
        rows = self._connection.execute(
            "SELECT id, source, source_ref, question, reviewers_json, channel, mode, context, requested_by, "
            "include_previous, status, error, conversation_id, created_at, finished_at "
            "FROM consultations WHERE status = ? ORDER BY created_at, id",
            (status,),
        ).fetchall()
        return [row_to_consultation(r) for r in rows]

    def count_since(self, source: str, source_ref: str, since: datetime) -> int:
        row = self._connection.execute(
            "SELECT count(*) FROM consultations WHERE source = ? AND source_ref = ? AND created_at >= ?",
            (source, source_ref, since.isoformat()),
        ).fetchone()
        return int(row[0])

    def claim(self, consultation_id: str) -> bool:
        cursor = self._connection.execute(
            "UPDATE consultations SET status = ? WHERE id = ? AND status = ?",
            (RUNNING, consultation_id, QUEUED),
        )
        self._commit_if_needed()
        return cursor.rowcount == 1

    def save_delivery(self, d: ConsultationDelivery) -> None:
        self._connection.execute(
            """
            INSERT INTO consultation_deliveries (
                id, consultation_id, participant_id, message_id, marker, status, attempts, error, delivered_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                message_id   = excluded.message_id,
                status       = excluded.status,
                attempts     = excluded.attempts,
                error        = excluded.error,
                delivered_at = excluded.delivered_at
            """,
            (d.id, d.consultation_id, d.participant_id, d.message_id, d.marker, d.status, d.attempts, d.error,
             d.delivered_at.isoformat() if d.delivered_at else None),
        )
        self._commit_if_needed()

    def list_deliveries(self, consultation_id: str) -> list[ConsultationDelivery]:
        rows = self._connection.execute(
            "SELECT id, consultation_id, participant_id, message_id, marker, status, attempts, error, delivered_at "
            "FROM consultation_deliveries WHERE consultation_id = ? ORDER BY participant_id, id",
            (consultation_id,),
        ).fetchall()
        return [row_to_delivery(r) for r in rows]
