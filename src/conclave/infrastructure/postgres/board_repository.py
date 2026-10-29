"""Board-Repository fuer PostgreSQL.

Die Verbindung laeuft mit ``autocommit`` (``api/server.py``): Jede Anweisung wird
einzeln festgeschrieben. Alles, was zusammengehoert, ist deshalb **eine**
Anweisung:

- Ticket anlegen: Die CTE erhoeht die Zaehler-Zeile des Projekts (Zeilensperre),
  das ``INSERT`` uebernimmt die Nummer. ``MAX(number)+1`` wuerde unter READ
  COMMITTED doppelte Nummern liefern.
- Projekt anlegen: Projekt und Zaehler-Zeile in einer CTE.
- Loeschen: ``ON DELETE CASCADE`` (in der Basisklasse).
- Kommentar/Verlauf: Zaehler erhoehen und ``seq`` uebernehmen in einer CTE.
- Ticket aendern bzw. ``next_task`` samt Verlauf: eine Anweisung. Der Zaehler steigt
  dabei einmal um die Zahl der Eintraege (dieselbe Zeile zweimal zu aendern geht in
  einer Anweisung nicht); die Eintraege bekommen die Werte darunter als ``seq``.

Wo der Aenderungszaehler nicht Teil der Anweisung ist (Projekt/Ticket anlegen,
Neunummerieren), folgt er als eigene Anweisung; dort ist er nur ein Signal fuer die UI.
"""

from __future__ import annotations

from contextlib import contextmanager

from conclave.domain.board import Project, Task, TaskComment, TaskEvent
from conclave.domain.board import POSITION_STEP
from conclave.infrastructure.sqlite.board_repository import SQLiteBoardRepository


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

    @contextmanager
    def _tx(self):
        yield                                     # autocommit; zusammengehoeriges ist eine Anweisung

    def _dt(self, value):
        return value

    def _bool(self, value) -> bool:
        return bool(value)

    def create_project(self, project: Project) -> None:
        self._execute(
            "WITH p AS (INSERT INTO board_projects (id, slug, name, created_at) VALUES (?, ?, ?, ?) RETURNING id) "
            "INSERT INTO board_counters (project_id, next_number) SELECT id, 1 FROM p",
            (project.id, project.slug, self._enc(project.name), project.created_at))
        self._bump()

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

    def add_comment(self, comment: TaskComment) -> None:
        self._execute(
            "WITH c AS (UPDATE board_meta SET value = value + 1 WHERE key = 'changes' RETURNING value) "
            "INSERT INTO board_comments (id, task_id, body, origin, actor_id, author_name, seq, "
            "created_at, updated_at) SELECT ?, ?, ?, ?, ?, ?, c.value, ?, ? FROM c",
            (comment.id, comment.task_id, self._enc(comment.body), comment.origin, comment.actor_id,
             self._enc(comment.author_name), comment.created_at, comment.updated_at))

    def add_event(self, event: TaskEvent) -> None:
        self._execute(
            "WITH c AS (UPDATE board_meta SET value = value + 1 WHERE key = 'changes' RETURNING value) "
            "INSERT INTO board_events (id, task_id, field, old_value, new_value, origin, actor_id, seq, "
            "created_at) SELECT ?, ?, ?, ?, ?, ?, ?, c.value, ? FROM c",
            (event.id, event.task_id, event.field_name, self._enc(event.old_value), self._enc(event.new_value),
             event.origin, event.actor_id, event.created_at))

    _EVENT_ROW = "SELECT ?, ?, ?, ?, ?, ?, ?, c.value - ?, ? FROM c, u"
    _UPDATE_WITH_EVENTS = (
        "WITH u AS (UPDATE board_tasks SET title = ?, description = ?, tags = ?, status = ?, position = ?, "
        "           human = ?, assignee = ?, updated_at = ?, version = version + 1 "
        "           WHERE id = ? AND version = ? RETURNING id), "
        "     c AS (UPDATE board_meta SET value = value + ? WHERE key = 'changes' "
        "           AND EXISTS (SELECT 1 FROM u) RETURNING value) "
        "INSERT INTO board_events (id, task_id, field, old_value, new_value, origin, actor_id, seq, created_at) ")

    def _event_rows(self, events) -> tuple[str, list]:
        """SELECT-Zeilen fuer board_events (feste Texte, Werte als Parameter);
        ``seq`` = Zaehlerstand - (Anzahl - Index)."""
        params = []
        n = len(events)
        for i, e in enumerate(events, start=1):
            params += [e.id, e.task_id, e.field_name, self._enc(e.old_value), self._enc(e.new_value),
                       e.origin, e.actor_id, n - i, e.created_at]
        return " UNION ALL ".join([self._EVENT_ROW] * n), params

    def update_task(self, task: Task, events=()) -> bool:
        events = list(events)
        if not events:
            return super().update_task(task)
        rows, params = self._event_rows(events)
        sql = self._UPDATE_WITH_EVENTS + rows  # nosec B608 - nur feste SQL-Texte, Werte als Platzhalter
        result = self._execute(sql, (*self._task_params(task), task.id, task.version, len(events) + 1, *params))
        if result.rowcount == len(events):
            task.version += 1
            return True
        return False

    def claim_task(self, task_id: str, from_status: str, to_status: str, position: float, updated_at,
                   event: TaskEvent | None = None) -> bool:
        if event is None:
            return super().claim_task(task_id, from_status, to_status, position, updated_at)
        _rows, params = self._event_rows([event])
        result = self._execute(
            "WITH u AS (UPDATE board_tasks SET status = ?, position = ?, updated_at = ?, version = version + 1 "
            "           WHERE id = ? AND status = ? AND NOT human RETURNING id), "
            "     c AS (UPDATE board_meta SET value = value + 2 WHERE key = 'changes' "
            "           AND EXISTS (SELECT 1 FROM u) RETURNING value) "
            "INSERT INTO board_events (id, task_id, field, old_value, new_value, origin, actor_id, seq, created_at) "
            "SELECT ?, ?, ?, ?, ?, ?, ?, c.value - ?, ? FROM c, u",
            (to_status, position, updated_at, task_id, from_status, *params))
        return result.rowcount == 1
