"""Board-Repository fuer PostgreSQL.

Die Verbindung laeuft mit ``autocommit``. Die Nummernvergabe ist deshalb eine
einzige Anweisung: Die CTE erhoeht die Zaehler-Zeile des Projekts (Zeilensperre)
und das ``INSERT`` uebernimmt die Nummer. ``MAX(number)+1`` wuerde unter
READ COMMITTED doppelte Nummern liefern.
"""

from __future__ import annotations

from conclave.domain.board import Task
from conclave.infrastructure.sqlite.board_repository import POSITION_STEP, SQLiteBoardRepository


class _Result:
    def __init__(self, rows, rowcount):
        self._rows, self.rowcount = rows, rowcount

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class PostgresBoardRepository(SQLiteBoardRepository):
    placeholder = "%s"

    def __init__(self, connection, crypto=None) -> None:
        super().__init__(connection, crypto, autocommit=False)

    def _execute(self, sql: str, params: tuple = ()):
        with self._connection.cursor() as cur:
            cur.execute(self._sql(sql), params)
            rows = cur.fetchall() if cur.description else []
            return _Result(rows, cur.rowcount)

    def _commit(self) -> None:
        pass                                    # autocommit

    def _dt(self, value):
        return value

    def _bool(self, value) -> bool:
        return bool(value)

    def create_task(self, task: Task) -> Task:
        row = self._one(
            "WITH n AS (UPDATE board_counters SET next_number = next_number + 1 WHERE project_id = ? "
            "           RETURNING next_number - 1 AS number) "
            "INSERT INTO board_tasks (id, project_id, number, title, description, tags, status, position, human, "
            "assignee, updated_at, created_at) "
            "SELECT ?, ?, n.number, ?, ?, ?, ?, ?, ?, ?, ?, ? FROM n RETURNING number",
            (task.project_id, task.id, task.project_id, *self._task_params(task), task.created_at))
        if row is None:
            raise ValueError("Unbekanntes Projekt")
        task.number = int(row[0])
        self._bump()
        return task

    def renumber_column(self, project_id: str, status: str) -> None:
        """Eine Anweisung: Postgres rechnet die Rangfolge auf dem Stand vor dem UPDATE aus."""
        self._execute(
            "UPDATE board_tasks t SET position = s.rn * ? FROM ("
            "  SELECT id, ROW_NUMBER() OVER (ORDER BY position, number) AS rn FROM board_tasks"
            "  WHERE project_id = ? AND status = ?) s WHERE s.id = t.id",
            (POSITION_STEP, project_id, status))
        self._bump()
