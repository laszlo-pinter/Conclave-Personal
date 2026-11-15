import json
from datetime import datetime

from conclave.domain.run import Run, UsageRecord


class PostgresRunRepository:
    def __init__(self, connection):
        self._connection = connection

    def save(self, run: Run) -> None:
        with self._connection.cursor() as cur:
            cur.execute(
                """
                INSERT INTO runs (
                    id, conversation_id, kind, participants, started_at,
                    finished_at, status, error
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(id) DO UPDATE SET
                    conversation_id=EXCLUDED.conversation_id,
                    kind=EXCLUDED.kind,
                    participants=EXCLUDED.participants,
                    started_at=EXCLUDED.started_at,
                    finished_at=EXCLUDED.finished_at,
                    status=EXCLUDED.status,
                    error=EXCLUDED.error
                """,
                (
                    run.id,
                    run.conversation_id,
                    run.kind,
                    json.dumps(run.participants),
                    run.started_at,
                    run.finished_at,
                    run.status,
                    run.error,
                ),
            )
            cur.execute("DELETE FROM usage_records WHERE run_id = %s", (run.id,))
            if run.usage is not None:
                cur.execute(
                    """
                    INSERT INTO usage_records (
                        id, run_id, conversation_id, participant_id, provider,
                        model, input_tokens, output_tokens, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        f"{run.id}:usage",
                        run.id,
                        run.conversation_id,
                        run.participants[0] if run.participants else "",
                        run.usage.provider,
                        run.usage.model,
                        run.usage.input_tokens,
                        run.usage.output_tokens,
                        run.finished_at or run.started_at,
                    ),
                )
        self._connection.commit()

    def get(self, run_id: str) -> Run | None:
        with self._connection.cursor() as cur:
            cur.execute(
                """
                SELECT r.id, r.conversation_id, r.kind, r.participants, r.started_at,
                       r.finished_at, r.status, r.error,
                       u.provider, u.model, u.input_tokens, u.output_tokens
                FROM runs r
                LEFT JOIN usage_records u ON u.run_id = r.id
                WHERE r.id = %s
                """,
                (run_id,),
            )
            row = cur.fetchone()
        return self._row_to_run(row) if row else None

    def list_all(self, limit: int = 100) -> list[Run]:
        with self._connection.cursor() as cur:
            cur.execute(
                """
                SELECT r.id, r.conversation_id, r.kind, r.participants, r.started_at,
                       r.finished_at, r.status, r.error,
                       u.provider, u.model, u.input_tokens, u.output_tokens
                FROM runs r
                LEFT JOIN usage_records u ON u.run_id = r.id
                ORDER BY r.started_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
        return [self._row_to_run(row) for row in rows]

    def list_by_conversation(self, conversation_id: str, limit: int = 100) -> list[Run]:
        with self._connection.cursor() as cur:
            cur.execute(
                """
                SELECT r.id, r.conversation_id, r.kind, r.participants, r.started_at,
                       r.finished_at, r.status, r.error,
                       u.provider, u.model, u.input_tokens, u.output_tokens
                FROM runs r
                LEFT JOIN usage_records u ON u.run_id = r.id
                WHERE r.conversation_id = %s
                ORDER BY r.started_at DESC
                LIMIT %s
                """,
                (conversation_id, limit),
            )
            rows = cur.fetchall()
        return [self._row_to_run(row) for row in rows]

    @staticmethod
    def _row_to_run(row) -> Run:
        usage = None
        if row[8] is not None:
            usage = UsageRecord(
                provider=row[8],
                model=row[9],
                input_tokens=row[10],
                output_tokens=row[11],
            )
        participants = row[3] if isinstance(row[3], list) else json.loads(row[3])
        return Run(
            id=row[0],
            conversation_id=row[1],
            kind=row[2],
            participants=participants,
            started_at=row[4] if isinstance(row[4], datetime) else datetime.fromisoformat(row[4]),
            finished_at=(row[5] if isinstance(row[5], datetime) else datetime.fromisoformat(row[5])) if row[5] else None,
            status=row[6],
            error=row[7],
            usage=usage,
        )

    # ── Budgets der Agenten (R11) ────────────────────────────────────────

    def mark_origin(self, conversation_id: str, since: datetime, origin: str) -> None:
        with self._connection.cursor() as cur:
            cur.execute("UPDATE runs SET origin = %s WHERE conversation_id = %s AND started_at >= %s "
                        "AND origin IS NULL", (origin, conversation_id, since))

    def tokens_since(self, since: datetime, *, origin: str | None = None,
                     conversation_id: str | None = None) -> int:
        sql = ("SELECT COALESCE(SUM(COALESCE(u.input_tokens, 0) + COALESCE(u.output_tokens, 0)), 0) "
               "FROM usage_records u JOIN runs r ON r.id = u.run_id WHERE r.started_at >= %s")
        params = [since]
        if origin is not None:
            sql += " AND r.origin = %s"
            params.append(origin)
        if conversation_id is not None:
            sql += " AND r.conversation_id = %s"
            params.append(conversation_id)
        with self._connection.cursor() as cur:
            cur.execute(sql, tuple(params))
            return int(cur.fetchone()[0])
