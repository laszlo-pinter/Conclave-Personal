import json
from datetime import datetime

from conclave.domain.run import Run, UsageRecord


class SQLiteRunRepository:
    def __init__(self, connection):
        self._connection = connection

    def save(self, run: Run) -> None:
        self._connection.execute(
            """
            INSERT INTO runs (
                id, conversation_id, kind, participants, started_at,
                finished_at, status, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                conversation_id=excluded.conversation_id,
                kind=excluded.kind,
                participants=excluded.participants,
                started_at=excluded.started_at,
                finished_at=excluded.finished_at,
                status=excluded.status,
                error=excluded.error
            """,
            (
                run.id,
                run.conversation_id,
                run.kind,
                json.dumps(run.participants),
                run.started_at.isoformat(),
                run.finished_at.isoformat() if run.finished_at else None,
                run.status,
                run.error,
            ),
        )
        self._connection.execute("DELETE FROM usage_records WHERE run_id = ?", (run.id,))
        if run.usage is not None:
            self._connection.execute(
                """
                INSERT INTO usage_records (
                    id, run_id, conversation_id, participant_id, provider,
                    model, input_tokens, output_tokens, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    (run.finished_at or run.started_at).isoformat(),
                ),
            )
        self._connection.commit()

    def get(self, run_id: str) -> Run | None:
        row = self._connection.execute(
            """
            SELECT r.id, r.conversation_id, r.kind, r.participants, r.started_at,
                   r.finished_at, r.status, r.error,
                   u.provider, u.model, u.input_tokens, u.output_tokens
            FROM runs r
            LEFT JOIN usage_records u ON u.run_id = r.id
            WHERE r.id = ?
            """,
            (run_id,),
        ).fetchone()
        return self._row_to_run(row) if row else None

    def list_all(self, limit: int = 100) -> list[Run]:
        rows = self._connection.execute(
            """
            SELECT r.id, r.conversation_id, r.kind, r.participants, r.started_at,
                   r.finished_at, r.status, r.error,
                   u.provider, u.model, u.input_tokens, u.output_tokens
            FROM runs r
            LEFT JOIN usage_records u ON u.run_id = r.id
            ORDER BY r.started_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._row_to_run(row) for row in rows]

    def list_by_conversation(self, conversation_id: str, limit: int = 100) -> list[Run]:
        rows = self._connection.execute(
            """
            SELECT r.id, r.conversation_id, r.kind, r.participants, r.started_at,
                   r.finished_at, r.status, r.error,
                   u.provider, u.model, u.input_tokens, u.output_tokens
            FROM runs r
            LEFT JOIN usage_records u ON u.run_id = r.id
            WHERE r.conversation_id = ?
            ORDER BY r.started_at DESC
            LIMIT ?
            """,
            (conversation_id, limit),
        ).fetchall()
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
        return Run(
            id=row[0],
            conversation_id=row[1],
            kind=row[2],
            participants=json.loads(row[3]),
            started_at=datetime.fromisoformat(row[4]),
            finished_at=datetime.fromisoformat(row[5]) if row[5] else None,
            status=row[6],
            error=row[7],
            usage=usage,
        )
