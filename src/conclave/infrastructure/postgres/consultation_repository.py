"""Consultations in PostgreSQL (Verbindung mit autocommit).

Das Limit pro Ticket und Stunde braucht Zaehlen und Einfuegen unter einer Sperre (R10).
Eine Transaktion auf der geteilten Verbindung waere unsicher (Anweisungen anderer Threads
liefen mit hinein), und eine einzelne Anweisung saehe unter READ COMMITTED nicht, was
waehrend des Wartens auf die Sperre festgeschrieben wurde. Deshalb: Sitzungssperre
``pg_advisory_lock`` je Ticket und Kanal (gegen andere Prozesse), ein Lock im Objekt
(gegen Threads derselben Verbindung, fuer die die Sitzungssperre wiedereintrittsfaehig
ist), dann ein ``INSERT ... WHERE count < limit`` mit frischem Snapshot.
"""

import json
import threading
from datetime import UTC, datetime

from conclave.domain.consultation import QUEUED, RUNNING, Consultation, ConsultationDelivery
from conclave.infrastructure.sqlite.consultation_repository import (
    COLUMNS,
    TERMINAL,
    row_to_consultation,
    row_to_delivery,
)


class PostgresConsultationRepository:
    def __init__(self, connection) -> None:
        self._connection = connection
        self._tx_lock = threading.Lock()

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
            f"SELECT {COLUMNS} FROM consultations "  # nosec B608 - feste Spaltenliste
            "WHERE id = %s",
            (consultation_id,), one=True)
        return row_to_consultation(row) if row else None

    def list_by_source_ref(self, source: str, source_ref: str) -> list[Consultation]:
        rows = self._fetch(
            f"SELECT {COLUMNS} FROM consultations "  # nosec B608 - feste Spaltenliste
            "WHERE source = %s AND source_ref = %s ORDER BY created_at DESC, id",
            (source, source_ref))
        return [row_to_consultation(r) for r in rows]

    def list_by_status(self, status: str) -> list[Consultation]:
        rows = self._fetch(
            f"SELECT {COLUMNS} FROM consultations "  # nosec B608 - feste Spaltenliste
            "WHERE status = %s ORDER BY created_at, id",
            (status,))
        return [row_to_consultation(r) for r in rows]

    def count_since(self, source: str, source_ref: str, since: datetime, channel: str | None = None) -> int:
        sql = "SELECT count(*) FROM consultations WHERE source = %s AND source_ref = %s AND created_at >= %s"
        params = [source, source_ref, since]
        if channel is not None:
            sql += " AND channel = %s"
            params.append(channel)
        return int(self._fetch(sql, tuple(params), one=True)[0])

    def create_if_under_limit(self, c: Consultation, since: datetime, limit: int) -> bool:
        key = f"consultation-limit:{c.source}:{c.source_ref}:{c.channel}"
        with self._tx_lock, self._connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(hashtext(%s))", (key,))
            try:
                cur.execute(
                    "INSERT INTO consultations (id, source, source_ref, question, reviewers_json, channel, mode, "
                    "context, requested_by, include_previous, status, error, conversation_id, created_at, "
                    "finished_at) SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s WHERE ("
                    "  SELECT count(*) FROM consultations WHERE source = %s AND source_ref = %s AND channel = %s "
                    "  AND created_at >= %s) < %s",
                    (c.id, c.source, c.source_ref, c.question, json.dumps(list(c.reviewers)), c.channel, c.mode,
                     c.context, c.requested_by, c.include_previous, c.status, c.error, c.conversation_id,
                     c.created_at, None, c.source, c.source_ref, c.channel, since, limit))
                return cur.rowcount == 1
            finally:
                cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", (key,))

    def set_conversation(self, consultation_id: str, conversation_id: str) -> None:
        with self._connection.cursor() as cur:
            cur.execute("UPDATE consultations SET conversation_id = %s WHERE id = %s",
                        (conversation_id, consultation_id))

    def transition(self, c: Consultation, from_status: str, to_status: str, *, error: str | None = None) -> bool:
        finished = datetime.now(UTC) if to_status in TERMINAL else None
        with self._connection.cursor() as cur:
            cur.execute("UPDATE consultations SET status = %s, error = %s, finished_at = %s "
                        "WHERE id = %s AND status = %s", (to_status, error, finished, c.id, from_status))
            if cur.rowcount == 1:
                c.status, c.error, c.finished_at = to_status, error, finished
                return True
            return False

    def claim(self, consultation_id: str, owner: str | None = None, lease_until: datetime | None = None) -> bool:
        with self._connection.cursor() as cur:
            cur.execute("UPDATE consultations SET status = %s, owner = %s, lease_until = %s "
                        "WHERE id = %s AND status = %s", (RUNNING, owner, lease_until, consultation_id, QUEUED))
            return cur.rowcount == 1

    def renew_lease(self, consultation_id: str, owner: str, lease_until: datetime) -> bool:
        with self._connection.cursor() as cur:
            cur.execute("UPDATE consultations SET lease_until = %s WHERE id = %s AND owner = %s AND status = %s",
                        (lease_until, consultation_id, owner, RUNNING))
            return cur.rowcount == 1

    def list_expired_running(self, now: datetime) -> list[Consultation]:
        rows = self._fetch(
            f"SELECT {COLUMNS} FROM consultations "  # nosec B608 - feste Spaltenliste
            "WHERE status = %s AND (lease_until IS NULL OR lease_until < %s) ORDER BY created_at, id",
            (RUNNING, now))
        return [row_to_consultation(r) for r in rows]

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
