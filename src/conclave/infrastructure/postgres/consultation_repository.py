import json
from datetime import datetime

from conclave.domain.consultation import QUEUED, RUNNING, Consultation, ConsultationDelivery
from conclave.infrastructure.sqlite.consultation_repository import row_to_consultation, row_to_delivery


class PostgresConsultationRepository:
    def __init__(self, connection) -> None:
        self._connection = connection

    def _fetch(self, sql: str, params: tuple, one: bool = False):
        with self._connection.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone() if one else cur.fetchall()

    def save(self, c: Consultation) -> None:
        with self._connection.cursor() as cur:
            cur.execute(
                """
                INSERT INTO consultations (
                    id, source, source_ref, question, reviewers_json, channel, mode, context,
                    requested_by, include_previous, status, error, conversation_id, created_at, finished_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(id) DO UPDATE SET
                    status          = EXCLUDED.status,
                    error           = EXCLUDED.error,
                    conversation_id = EXCLUDED.conversation_id,
                    finished_at     = EXCLUDED.finished_at
                """,
                (c.id, c.source, c.source_ref, c.question, json.dumps(list(c.reviewers)), c.channel, c.mode,
                 c.context, c.requested_by, c.include_previous, c.status, c.error, c.conversation_id,
                 c.created_at, c.finished_at),
            )

    def get(self, consultation_id: str) -> Consultation | None:
        row = self._fetch(
            "SELECT id, source, source_ref, question, reviewers_json, channel, mode, context, requested_by, "
            "include_previous, status, error, conversation_id, created_at, finished_at "
            "FROM consultations WHERE id = %s",
            (consultation_id,), one=True)
        return row_to_consultation(row) if row else None

    def list_by_source_ref(self, source: str, source_ref: str) -> list[Consultation]:
        rows = self._fetch(
            "SELECT id, source, source_ref, question, reviewers_json, channel, mode, context, requested_by, "
            "include_previous, status, error, conversation_id, created_at, finished_at "
            "FROM consultations WHERE source = %s AND source_ref = %s ORDER BY created_at DESC, id",
            (source, source_ref))
        return [row_to_consultation(r) for r in rows]

    def list_by_status(self, status: str) -> list[Consultation]:
        rows = self._fetch(
            "SELECT id, source, source_ref, question, reviewers_json, channel, mode, context, requested_by, "
            "include_previous, status, error, conversation_id, created_at, finished_at "
            "FROM consultations WHERE status = %s ORDER BY created_at, id",
            (status,))
        return [row_to_consultation(r) for r in rows]

    def count_since(self, source: str, source_ref: str, since: datetime) -> int:
        row = self._fetch(
            "SELECT count(*) FROM consultations WHERE source = %s AND source_ref = %s AND created_at >= %s",
            (source, source_ref, since), one=True)
        return int(row[0])

    def claim(self, consultation_id: str) -> bool:
        with self._connection.cursor() as cur:
            cur.execute("UPDATE consultations SET status = %s WHERE id = %s AND status = %s",
                        (RUNNING, consultation_id, QUEUED))
            return cur.rowcount == 1

    def save_delivery(self, d: ConsultationDelivery) -> None:
        with self._connection.cursor() as cur:
            cur.execute(
                """
                INSERT INTO consultation_deliveries (
                    id, consultation_id, participant_id, message_id, marker, status, attempts, error, delivered_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(id) DO UPDATE SET
                    message_id   = EXCLUDED.message_id,
                    status       = EXCLUDED.status,
                    attempts     = EXCLUDED.attempts,
                    error        = EXCLUDED.error,
                    delivered_at = EXCLUDED.delivered_at
                """,
                (d.id, d.consultation_id, d.participant_id, d.message_id, d.marker, d.status, d.attempts, d.error,
                 d.delivered_at),
            )

    def list_deliveries(self, consultation_id: str) -> list[ConsultationDelivery]:
        rows = self._fetch(
            "SELECT id, consultation_id, participant_id, message_id, marker, status, attempts, error, delivered_at "
            "FROM consultation_deliveries WHERE consultation_id = %s ORDER BY participant_id, id",
            (consultation_id,))
        return [row_to_delivery(r) for r in rows]
