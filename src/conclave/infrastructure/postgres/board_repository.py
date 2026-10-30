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

Wo der Aenderungszaehler nicht Teil der Anweisung ist (Neunummerieren), folgt er als
eigene Anweisung; dort ist er nur ein Signal fuer die UI.

R9: Anlegen samt Ereignis ``created``, Kommentar aendern/loeschen samt Verlauf, Ticket
loeschen samt Eintrag im Projekt-Verlauf und Projekt anlegen/umbenennen samt Verlauf
sind ebenfalls je eine Anweisung.
"""

from __future__ import annotations

from contextlib import contextmanager

from conclave.domain.board import Project, ProjectEvent, Task, TaskComment, TaskEvent
from conclave.domain.board import POSITION_STEP
from conclave.infrastructure.sqlite.board_repository import SQLiteBoardRepository

_TASK_INSERT_COLUMNS = ("id, project_id, number, title, description, tags, status, position, rank, human, "
                        "assignee, updated_at, created_at, origin, actor_id, created_by")
_EVENT_COLUMNS = "id, task_id, field, old_value, new_value, origin, actor_id, seq, created_at"
_PROJECT_EVENT_COLUMNS = "id, project_id, field, old_value, new_value, origin, actor_id, seq, created_at"


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

    def create_project(self, project: Project, event: ProjectEvent | None = None) -> None:
        if event is None:
            self._execute(
                "WITH p AS (INSERT INTO board_projects (id, slug, name, created_at) VALUES (?, ?, ?, ?) "
                "           RETURNING id) "
                "INSERT INTO board_counters (project_id, next_number) SELECT id, 1 FROM p",
                (project.id, project.slug, self._enc(project.name), project.created_at))
            self._bump()
            return
        self._execute(
            "WITH p AS (INSERT INTO board_projects (id, slug, name, created_at) VALUES (?, ?, ?, ?) RETURNING id), "
            "     k AS (INSERT INTO board_counters (project_id, next_number) SELECT id, 1 FROM p), "
            "     c AS (UPDATE board_meta SET value = value + 1 WHERE key = 'changes' RETURNING value) "
            f"INSERT INTO board_project_events ({_PROJECT_EVENT_COLUMNS}) "  # nosec B608 - feste Texte
            "SELECT ?, p.id, ?, ?, ?, ?, ?, c.value, ? FROM p, c",
            (project.id, project.slug, self._enc(project.name), project.created_at, event.id, event.field_name,
             self._enc(event.old_value), self._enc(event.new_value), event.origin, event.actor_id,
             event.created_at))

    def rename_project(self, slug: str, name: str, event: ProjectEvent | None = None) -> bool:
        if event is None:
            return super().rename_project(slug, name)
        result = self._execute(
            "WITH u AS (UPDATE board_projects SET name = ? WHERE slug = ? RETURNING id), "
            "     c AS (UPDATE board_meta SET value = value + 1 WHERE key = 'changes' "
            "           AND EXISTS (SELECT 1 FROM u) RETURNING value) "
            f"INSERT INTO board_project_events ({_PROJECT_EVENT_COLUMNS}) "  # nosec B608 - feste Texte
            "SELECT ?, u.id, ?, ?, ?, ?, ?, c.value, ? FROM u, c",
            (self._enc(name), slug, event.id, event.field_name, self._enc(event.old_value),
             self._enc(event.new_value), event.origin, event.actor_id, event.created_at))
        return result.rowcount == 1

    def create_task(self, task: Task, event: TaskEvent | None = None) -> Task:
        values = (task.id, task.project_id, *self._task_params(task), task.created_at, task.origin,
                  task.actor_id, task.created_by or "")
        if event is None:
            row = self._one(
                "WITH n AS (UPDATE board_counters SET next_number = next_number + 1 WHERE project_id = ? "
                "           RETURNING next_number - 1 AS number) "
                f"INSERT INTO board_tasks ({_TASK_INSERT_COLUMNS}) "  # nosec B608 - feste Texte
                "SELECT ?, ?, n.number, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ? FROM n RETURNING number",
                (task.project_id, *values))
            if row is None:
                raise ValueError("Unbekanntes Projekt")
            self._bump()
        else:
            row = self._one(
                "WITH n AS (UPDATE board_counters SET next_number = next_number + 1 WHERE project_id = ? "
                "           RETURNING next_number - 1 AS number), "
                f"     t AS (INSERT INTO board_tasks ({_TASK_INSERT_COLUMNS}) "  # nosec B608 - feste Texte
                "           SELECT ?, ?, n.number, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ? FROM n "
                "           RETURNING id, number), "
                "     c AS (UPDATE board_meta SET value = value + 2 WHERE key = 'changes' "
                "           AND EXISTS (SELECT 1 FROM t) RETURNING value), "
                f"     e AS (INSERT INTO board_events ({_EVENT_COLUMNS}) "  # nosec B608 - feste Texte
                "           SELECT ?, t.id, ?, ?, ?, ?, ?, c.value, ? FROM t, c) "
                "SELECT number FROM t",
                (task.project_id, *values, event.id, event.field_name, self._enc(event.old_value),
                 self._enc(event.new_value), event.origin, event.actor_id, event.created_at))
            if row is None:
                raise ValueError("Unbekanntes Projekt")
        task.number = int(row[0])
        return task

    _IMPORT_TASK = (
        f"WITH u AS (INSERT INTO board_tasks ({_TASK_INSERT_COLUMNS}) "  # nosec B608 - feste Texte
        "           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "           ON CONFLICT (project_id, number) DO NOTHING RETURNING id, project_id, number), "
        "     n AS (UPDATE board_counters SET next_number = GREATEST(next_number, (SELECT number FROM u) + 1) "
        "           WHERE project_id = (SELECT project_id FROM u) RETURNING project_id), "
        "     c AS (UPDATE board_meta SET value = value + ? WHERE key = 'changes' "
        "           AND EXISTS (SELECT 1 FROM u) RETURNING value), "
        f"     e AS (INSERT INTO board_events ({_EVENT_COLUMNS}) "
        "           SELECT ?, u.id, ?, ?, ?, ?, ?, c.value - ?, ? FROM u, c WHERE ?) ")
    _COMMENT_ROW = "SELECT ?, ?, ?, ?, ?, ?, c.value - ?, ?::timestamptz, ?::timestamptz FROM c, u"  # Typen fuer NULL im UNION

    def import_task(self, task: Task, comments=(), event: TaskEvent | None = None) -> bool:
        """Ticket mit vorgegebener Nummer, Zaehler-Sprung, Kommentaren und Ereignis ``created`` in
        einer Anweisung; ``False``, wenn die Nummer inzwischen vergeben ist (dann wird nichts geschrieben)."""
        comments = list(comments)
        n = len(comments)
        params = [task.id, task.project_id, task.number, *self._task_params(task), task.created_at,
                  task.origin, task.actor_id, task.created_by or "", n + 2]
        if event is not None:
            params += [event.id, event.field_name, self._enc(event.old_value), self._enc(event.new_value),
                       event.origin, event.actor_id, n + 1, event.created_at, True]
        else:
            params += [None, "created", None, None, None, None, n + 1, task.created_at, False]
        if comments:
            rows = " UNION ALL ".join([self._COMMENT_ROW] * len(comments))
            for i, cm in enumerate(comments, start=1):
                params += [cm.id, cm.task_id, self._enc(cm.body), cm.origin, cm.actor_id,
                           self._enc(cm.author_name), len(comments) - i, cm.created_at, cm.updated_at]
            sql = (self._IMPORT_TASK + "INSERT INTO board_comments (id, task_id, body, origin, actor_id, "  # nosec B608 - feste Texte
                   "author_name, seq, created_at, updated_at) " + rows)  # nosec B608 - feste Texte, Platzhalter
        else:
            sql = self._IMPORT_TASK + "SELECT 1 FROM c, u"  # nosec B608 - feste Texte
        result = self._execute(sql, tuple(params))
        return result.rowcount == (len(comments) or 1)

    def renumber_column(self, project_id: str, status: str) -> None:
        """Eine Anweisung: Postgres rechnet die Rangfolge auf dem Stand vor dem UPDATE aus."""
        self._execute(
            "UPDATE board_tasks t SET position = s.rn * ? FROM ("
            "  SELECT id, ROW_NUMBER() OVER (ORDER BY position, number) AS rn FROM board_tasks"
            "  WHERE project_id = ? AND status = ?) s WHERE s.id = t.id",
            (POSITION_STEP, project_id, status))
        self._bump()

    def renumber_ranks(self, project_id: str) -> None:
        """Eine Anweisung, wie renumber_column."""
        self._execute(
            "UPDATE board_tasks t SET rank = s.rn * ? FROM ("
            "  SELECT id, ROW_NUMBER() OVER (ORDER BY rank, number) AS rn FROM board_tasks"
            "  WHERE project_id = ?) s WHERE s.id = t.id",
            (POSITION_STEP, project_id))
        self._bump()

    def add_comment(self, comment: TaskComment, *, only_if_not_human: bool = False) -> bool:
        result = self._execute(
            "WITH t AS (SELECT 1 FROM board_tasks WHERE id = ? AND (NOT human OR ?)), "
            "     c AS (UPDATE board_meta SET value = value + 1 WHERE key = 'changes' "
            "           AND EXISTS (SELECT 1 FROM t) RETURNING value) "
            "INSERT INTO board_comments (id, task_id, body, origin, actor_id, author_name, seq, "
            "created_at, updated_at) SELECT ?, ?, ?, ?, ?, ?, c.value, ?, ? FROM c",
            (comment.task_id, not only_if_not_human, comment.id, comment.task_id, self._enc(comment.body),
             comment.origin, comment.actor_id, self._enc(comment.author_name), comment.created_at,
             comment.updated_at))
        return result.rowcount == 1

    def add_comment_checked(self, comment: TaskComment, *, only_if_not_human: bool = False) -> bool:
        return self.add_comment(comment, only_if_not_human=only_if_not_human)

    def _comment_change(self, set_clause: str, set_params: tuple, comment_id: str, event: TaskEvent) -> bool:
        result = self._execute(
            f"WITH u AS (UPDATE board_comments SET {set_clause} "  # nosec B608 - feste Texte
            "           WHERE id = ? AND deleted_at IS NULL RETURNING task_id), "
            "     c AS (UPDATE board_meta SET value = value + 1 WHERE key = 'changes' "
            "           AND EXISTS (SELECT 1 FROM u) RETURNING value) "
            f"INSERT INTO board_events ({_EVENT_COLUMNS}) "  # nosec B608 - feste Texte
            "SELECT ?, u.task_id, ?, ?, ?, ?, ?, c.value, ? FROM u, c",
            (*set_params, comment_id, event.id, event.field_name, self._enc(event.old_value),
             self._enc(event.new_value), event.origin, event.actor_id, event.created_at))
        return result.rowcount == 1

    def update_comment(self, comment: TaskComment, event: TaskEvent | None = None) -> bool:
        if event is None:
            return super().update_comment(comment)
        return self._comment_change("body = ?, updated_at = ?", (self._enc(comment.body), comment.updated_at),
                                    comment.id, event)

    def delete_comment(self, comment_id: str, deleted_at=None, event: TaskEvent | None = None) -> bool:
        if event is None:
            return super().delete_comment(comment_id, deleted_at)
        return self._comment_change("body = '', deleted_at = ?", (deleted_at,), comment_id, event)

    def delete_task(self, task_id: str, tombstone: ProjectEvent | None = None) -> bool:
        if tombstone is None:
            return super().delete_task(task_id)
        result = self._execute(
            "WITH d AS (DELETE FROM board_tasks WHERE id = ? RETURNING project_id), "
            "     c AS (UPDATE board_meta SET value = value + 2 WHERE key = 'changes' "
            "           AND EXISTS (SELECT 1 FROM d) RETURNING value) "
            f"INSERT INTO board_project_events ({_PROJECT_EVENT_COLUMNS}) "  # nosec B608 - feste Texte
            "SELECT ?, d.project_id, ?, ?, ?, ?, ?, c.value, ? FROM d, c",
            (task_id, tombstone.id, tombstone.field_name, self._enc(tombstone.old_value),
             self._enc(tombstone.new_value), tombstone.origin, tombstone.actor_id, tombstone.created_at))
        return result.rowcount == 1

    def add_event(self, event: TaskEvent) -> None:
        self._execute(
            "WITH c AS (UPDATE board_meta SET value = value + 1 WHERE key = 'changes' RETURNING value) "
            "INSERT INTO board_events (id, task_id, field, old_value, new_value, origin, actor_id, seq, "
            "created_at) SELECT ?, ?, ?, ?, ?, ?, ?, c.value, ? FROM c",
            (event.id, event.task_id, event.field_name, self._enc(event.old_value), self._enc(event.new_value),
             event.origin, event.actor_id, event.created_at))

    _EVENT_ROW = "SELECT ?, ?, ?, ?, ?, ?, ?, c.value - ?, ?::timestamptz FROM c, u"
    _UPDATE_WITH_EVENTS = (
        "WITH u AS (UPDATE board_tasks SET title = ?, description = ?, tags = ?, status = ?, position = ?, "
        "           rank = ?, human = ?, assignee = ?, updated_at = ?, version = version + 1 "
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
