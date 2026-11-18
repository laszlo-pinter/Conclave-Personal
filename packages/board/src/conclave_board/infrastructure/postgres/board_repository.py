# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Laszlo Pinter

"""Board-Repository fuer PostgreSQL.

Transaktionsmodell (T2): **Jeder Schreibvorgang ist eine Transaktion** (``_tx`` bzw.
``@_transactional``) auf einer Verbindung, die fuer die Dauer an den Thread gebunden
ist (``pool.PooledConnection`` im Server, ``pool.DirectConnection`` ueber einer
einzelnen Verbindung). Verschachtelte Aufrufe schliessen sich der aeusseren
Transaktion an. ``locked_task`` sperrt die Ticket-Zeile (``SELECT ... FOR UPDATE``)
fuer Regeln vom Typ "erst pruefen, dann schreiben"; alles, was darin geschieht, laeuft
in derselben Transaktion.

Die Anweisungen selbst bleiben, wo es sie schon gab, CTEs: Sie halten die Zahl der
Rundreisen klein und sind fuer sich korrekt unter READ COMMITTED, z. B.:

- Ticket anlegen: Die CTE erhoeht die Zaehler-Zeile des Projekts (Zeilensperre),
  das ``INSERT`` uebernimmt die Nummer. ``MAX(number)+1`` wuerde doppelte Nummern liefern.
- Kommentar/Verlauf: Zaehler erhoehen und ``seq`` uebernehmen in einer CTE.
- Ticket aendern bzw. ``next_task`` samt Verlauf: eine bedingte Anweisung (Version
  bzw. Ausgangsspalte); der Zaehler steigt einmal um die Zahl der Eintraege.
- Loeschen: ``ON DELETE CASCADE``.
"""

from __future__ import annotations

from contextlib import contextmanager
from functools import wraps

from conclave_board.domain.board import Initiative, Project, ProjectEvent, Task, TaskComment, TaskEvent
from conclave_board.domain.board import POSITION_STEP
from conclave_board.infrastructure.postgres.pool import as_transactional
from conclave_board.infrastructure.sqlite.board_repository import SQLiteBoardRepository

_TASK_INSERT_COLUMNS = ("id, project_id, number, title, description, tags, status, position, rank, human, "
                        "assignee, updated_at, created_at, origin, actor_id, created_by, kind, control, control_scope")
_TASK_INSERT_INITIATIVE = _TASK_INSERT_COLUMNS + ", initiative_id, initiative_number"
_EVENT_COLUMNS = "id, task_id, field, old_value, new_value, origin, actor_id, seq, created_at"
_PROJECT_EVENT_COLUMNS = "id, project_id, field, old_value, new_value, origin, actor_id, seq, created_at"


class _Result:
    def __init__(self, rows, rowcount):
        self._rows, self.rowcount = rows, rowcount

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _Conflict(Exception):
    """Das Ticket wurde inzwischen geaendert; die Transaktion wird zurueckgerollt."""


def _transactional(method):
    """Der Schreibvorgang laeuft in einer Transaktion (oder in der schon offenen)."""
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._tx():
            return method(self, *args, **kwargs)
    return wrapper


class PostgresBoardRepository(SQLiteBoardRepository):
    placeholder = "%s"

    def __init__(self, connection, crypto=None) -> None:
        # Rohe psycopg2-Verbindungen (Tests, CLI) bekommen dieselbe Transaktions-Schnittstelle
        super().__init__(as_transactional(connection), crypto, autocommit=False)

    def _execute(self, sql: str, params: tuple = ()):
        with self._connection.cursor() as cur:
            cur.execute(self._sql(sql), params)
            rows = cur.fetchall() if cur.description else []
            return _Result(rows, cur.rowcount)

    @contextmanager
    def _tx(self):
        with self._connection.transaction():
            yield

    @contextmanager
    def locked_key(self, key: str):
        """Transaktion unter ``pg_advisory_xact_lock(hashtext(key))`` (T5); faellt mit Commit oder Rollback."""
        with self._tx():
            self._execute("SELECT pg_advisory_xact_lock(hashtext(?))", ("board:" + key,))
            yield

    @contextmanager
    def locked_task(self, task_id: str):
        """Transaktion mit Zeilensperre auf das Ticket (``FOR UPDATE``); ``True``, wenn es existiert.

        Parallele Aufrufe fuer dasselbe Ticket warten, bis die erste Transaktion endet; was
        darin gelesen wird, aendert sonst niemand. Grundlage fuer die Regeln aus T5."""
        with self._tx():
            row = self._one("SELECT id FROM board_tasks WHERE id = ? FOR UPDATE", (task_id,))
            yield row is not None

    def _dt(self, value):
        return value

    def _bool(self, value) -> bool:
        return bool(value)

    @_transactional
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

    @_transactional
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

    @_transactional
    def create_task(self, task: Task, event: TaskEvent | None = None) -> Task:
        values = (task.id, task.project_id, *self._task_params(task), *self._origin_params(task))
        if task.initiative_id:
            return self._create_task_in_initiative(task, values, event)
        if event is None:
            row = self._one(
                "WITH n AS (UPDATE board_counters SET next_number = next_number + 1 WHERE project_id = ? "
                "           RETURNING next_number - 1 AS number) "
                f"INSERT INTO board_tasks ({_TASK_INSERT_COLUMNS}) "  # nosec B608 - feste Texte
                "SELECT ?, ?, n.number, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ? FROM n RETURNING number",
                (task.project_id, *values))
            if row is None:
                raise ValueError("Unbekanntes Projekt")
            self._bump()
        else:
            row = self._one(
                "WITH n AS (UPDATE board_counters SET next_number = next_number + 1 WHERE project_id = ? "
                "           RETURNING next_number - 1 AS number), "
                f"     t AS (INSERT INTO board_tasks ({_TASK_INSERT_COLUMNS}) "  # nosec B608 - feste Texte
                "           SELECT ?, ?, n.number, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ? FROM n "
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

    def _create_task_in_initiative(self, task: Task, values: tuple, event: TaskEvent | None) -> Task:
        """Projekt- und Vorhaben-Nummer in einer Anweisung; ohne Vorhaben-Zeile kein Ticket."""
        event_cte, event_params, bump = "", (), 1
        if event is not None:
            bump = 2
            event_cte = (f", e AS (INSERT INTO board_events ({_EVENT_COLUMNS}) "  # nosec B608 - feste Texte
                         "SELECT ?, t.id, ?, ?, ?, ?, ?, c.value, ? FROM t, c) ")
            event_params = (event.id, event.field_name, self._enc(event.old_value), self._enc(event.new_value),
                            event.origin, event.actor_id, event.created_at)
        row = self._one(
            "WITH n AS (UPDATE board_counters SET next_number = next_number + 1 WHERE project_id = ? "
            "           RETURNING next_number - 1 AS number), "
            "     m AS (UPDATE board_initiatives SET next_number = next_number + 1 WHERE id = ? "
            "           RETURNING next_number - 1 AS number), "
            f"     t AS (INSERT INTO board_tasks ({_TASK_INSERT_INITIATIVE}) "  # nosec B608 - feste Texte
            "           SELECT ?, ?, n.number, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, m.number FROM n, m "
            "           RETURNING id, number, initiative_number), "
            "     c AS (UPDATE board_meta SET value = value + ? WHERE key = 'changes' "
            "           AND EXISTS (SELECT 1 FROM t) RETURNING value)"
            + event_cte +
            " SELECT number, initiative_number FROM t",
            (task.project_id, task.initiative_id, *values, task.initiative_id, bump, *event_params))
        if row is None:
            raise ValueError("Unbekanntes Projekt oder Vorhaben")
        task.number, task.initiative_number = int(row[0]), int(row[1])
        return task

    @_transactional
    def create_initiative(self, initiative: Initiative, event: ProjectEvent | None = None) -> None:
        if event is None:
            super().create_initiative(initiative)
            return
        self._execute(
            "WITH i AS (INSERT INTO board_initiatives (id, project_id, slug, title, rank, next_number, created_at) "
            "           VALUES (?, ?, ?, ?, ?, 1, ?) RETURNING project_id), "
            "     c AS (UPDATE board_meta SET value = value + 1 WHERE key = 'changes' RETURNING value) "
            f"INSERT INTO board_project_events ({_PROJECT_EVENT_COLUMNS}) "  # nosec B608 - feste Texte
            "SELECT ?, i.project_id, ?, ?, ?, ?, ?, c.value, ? FROM i, c",
            (initiative.id, initiative.project_id, initiative.slug, self._enc(initiative.title), initiative.rank,
             initiative.created_at, event.id, event.field_name, self._enc(event.old_value),
             self._enc(event.new_value), event.origin, event.actor_id, event.created_at))

    @_transactional
    def update_initiative(self, initiative: Initiative, events=()) -> None:
        events = list(events)
        if len(events) != 1:
            raise ValueError("Ein Vorhaben aendert sich mit genau einem Verlaufseintrag.")
        event = events[0]
        self._execute(
            "WITH u AS (UPDATE board_initiatives SET title = ?, rank = ? WHERE id = ? RETURNING project_id), "
            "     c AS (UPDATE board_meta SET value = value + 1 WHERE key = 'changes' "
            "           AND EXISTS (SELECT 1 FROM u) RETURNING value) "
            f"INSERT INTO board_project_events ({_PROJECT_EVENT_COLUMNS}) "  # nosec B608 - feste Texte
            "SELECT ?, u.project_id, ?, ?, ?, ?, ?, c.value, ? FROM u, c",
            (self._enc(initiative.title), initiative.rank, initiative.id, event.id, event.field_name,
             self._enc(event.old_value), self._enc(event.new_value), event.origin, event.actor_id,
             event.created_at))

    def assign_initiative(self, task: Task, initiative: Initiative | None, event: TaskEvent) -> bool:
        try:
            with self._tx():
                return self._assign_initiative(task, initiative, event)
        except _Conflict:
            return False

    def _assign_initiative(self, task: Task, initiative: Initiative | None, event: TaskEvent) -> bool:
        """Zwei Anweisungen in einer Transaktion: Die Nummer wird nur vergeben, wenn das Ticket noch
        diese Version hat; dann Ticket, Zaehler und Verlauf. Aendert jemand das Ticket genau dazwischen,
        wird alles zurueckgerollt (keine Luecke im Vorhaben). Den Verlaufswert verschluesselt die App,
        deshalb steht die Nummer vorher fest. Laeuft schon eine aeussere Transaktion (``locked_task``),
        schreibt sie den Zaehler fest; dann bleibt wie vor T2 eine Luecke, nie eine doppelte Nummer."""
        number = None
        if initiative is not None:
            row = self._one(
                "UPDATE board_initiatives SET next_number = next_number + 1 WHERE id = ? "
                "AND EXISTS (SELECT 1 FROM board_tasks WHERE id = ? AND version = ?) "
                "RETURNING next_number - 1", (initiative.id, task.id, task.version))
            if row is None:
                raise _Conflict
            number = int(row[0])
            event.new_value = f"{task.project_slug}/{initiative.slug}-{number}"
        result = self._execute(
            "WITH u AS (UPDATE board_tasks SET initiative_id = ?, initiative_number = ?, updated_at = ?, "
            "           version = version + 1 WHERE id = ? AND version = ? RETURNING id), "
            "     c AS (UPDATE board_meta SET value = value + 2 WHERE key = 'changes' "
            "           AND EXISTS (SELECT 1 FROM u) RETURNING value) "
            f"INSERT INTO board_events ({_EVENT_COLUMNS}) "  # nosec B608 - feste Texte
            "SELECT ?, u.id, ?, ?, ?, ?, ?, c.value, ? FROM u, c",
            (initiative.id if initiative else None, number, task.updated_at, task.id, task.version,
             event.id, event.field_name, self._enc(event.old_value), self._enc(event.new_value), event.origin,
             event.actor_id, event.created_at))
        if result.rowcount != 1:
            raise _Conflict                       # Zaehler nicht stehen lassen: Rollback
        return True

    _IMPORT_TASK = (
        f"WITH u AS (INSERT INTO board_tasks ({_TASK_INSERT_COLUMNS}) "  # nosec B608 - feste Texte
        "           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "           ON CONFLICT (project_id, number) DO NOTHING RETURNING id, project_id, number), "
        "     n AS (UPDATE board_counters SET next_number = GREATEST(next_number, (SELECT number FROM u) + 1) "
        "           WHERE project_id = (SELECT project_id FROM u) RETURNING project_id), "
        "     c AS (UPDATE board_meta SET value = value + ? WHERE key = 'changes' "
        "           AND EXISTS (SELECT 1 FROM u) RETURNING value), "
        f"     e AS (INSERT INTO board_events ({_EVENT_COLUMNS}) "
        "           SELECT ?, u.id, ?, ?, ?, ?, ?, c.value - ?, ? FROM u, c WHERE ?) ")
    _COMMENT_ROW = "SELECT ?, ?, ?, ?, ?, ?, c.value - ?, ?::timestamptz, ?::timestamptz FROM c, u"  # Typen fuer NULL im UNION

    @_transactional
    def import_task(self, task: Task, comments=(), event: TaskEvent | None = None) -> bool:
        """Ticket mit vorgegebener Nummer, Zaehler-Sprung, Kommentaren und Ereignis ``created`` in
        einer Anweisung; ``False``, wenn die Nummer inzwischen vergeben ist (dann wird nichts geschrieben)."""
        comments = list(comments)
        n = len(comments)
        params = [task.id, task.project_id, task.number, *self._task_params(task), *self._origin_params(task),
                  n + 2]
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

    @_transactional
    def renumber_column(self, project_id: str, status: str) -> None:
        """Eine Anweisung: Postgres rechnet die Rangfolge auf dem Stand vor dem UPDATE aus."""
        self._execute(
            "UPDATE board_tasks t SET position = s.rn * ?, version = t.version + 1 FROM ("
            "  SELECT id, ROW_NUMBER() OVER (ORDER BY position, number) AS rn FROM board_tasks"
            "  WHERE project_id = ? AND status = ?) s WHERE s.id = t.id",
            (POSITION_STEP, project_id, status))
        self._bump()

    @_transactional
    def renumber_ranks(self, project_id: str) -> None:
        """Eine Anweisung, wie renumber_column."""
        self._execute(
            "UPDATE board_tasks t SET rank = s.rn * ?, version = t.version + 1 FROM ("
            "  SELECT id, ROW_NUMBER() OVER (ORDER BY rank, number) AS rn FROM board_tasks"
            "  WHERE project_id = ?) s WHERE s.id = t.id",
            (POSITION_STEP, project_id))
        self._bump()

    @_transactional
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

    @_transactional
    def update_comment(self, comment: TaskComment, event: TaskEvent | None = None) -> bool:
        if event is None:
            return super().update_comment(comment)
        return self._comment_change("body = ?, updated_at = ?", (self._enc(comment.body), comment.updated_at),
                                    comment.id, event)

    @_transactional
    def delete_comment(self, comment_id: str, deleted_at=None, event: TaskEvent | None = None) -> bool:
        if event is None:
            return super().delete_comment(comment_id, deleted_at)
        return self._comment_change("body = '', deleted_at = ?", (deleted_at,), comment_id, event)

    @_transactional
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

    @_transactional
    def add_event(self, event: TaskEvent) -> None:
        self._execute(
            "WITH c AS (UPDATE board_meta SET value = value + 1 WHERE key = 'changes' RETURNING value) "
            "INSERT INTO board_events (id, task_id, field, old_value, new_value, origin, actor_id, seq, "
            "created_at) SELECT ?, ?, ?, ?, ?, ?, ?, c.value, ? FROM c",
            (event.id, event.task_id, event.field_name, self._enc(event.old_value), self._enc(event.new_value),
             event.origin, event.actor_id, event.created_at))

    _EVENT_ROW = "SELECT ?, ?, ?, ?, ?, ?, ?, c.value - ?, ?::timestamptz FROM c, u"
    _UPDATE_TASK_CTE = (
        "WITH u AS (UPDATE board_tasks SET title = ?, description = ?, tags = ?, status = ?, position = ?, "
        "           rank = ?, human = ?, assignee = ?, updated_at = ?, review_state = ?, review_at = ?, "
        "           review_red_count = ?, review_blocking = ?, review_suggestions = ?, review_checked = ?, "
        "           control_ack_by = ?, control_ack_at = ?, version = version + 1 "
        "           WHERE id = ? AND version = ? RETURNING id), "
        "     c AS (UPDATE board_meta SET value = value + ? WHERE key = 'changes' "
        "           AND EXISTS (SELECT 1 FROM u) RETURNING value) ")
    _UPDATE_WITH_EVENTS = (
        _UPDATE_TASK_CTE
        + "INSERT INTO board_events (id, task_id, field, old_value, new_value, origin, actor_id, seq, created_at) ")
    # Mit Kommentar (Review-Ergebnis, P3): der Kommentar als eigene CTE, seq unterhalb der Eintraege
    _UPDATE_WITH_COMMENT = (
        _UPDATE_TASK_CTE
        + "   , k AS (INSERT INTO board_comments (id, task_id, body, origin, actor_id, author_name, seq, "  # nosec B608 - feste Texte
          "           created_at, updated_at) SELECT ?, ?, ?, ?, ?, ?, c.value - ?, ?, ? FROM c, u) "
        + "INSERT INTO board_events (id, task_id, field, old_value, new_value, origin, actor_id, seq, created_at) ")

    def _event_rows(self, events) -> tuple[str, list]:
        """SELECT-Zeilen fuer board_events (feste Texte, Werte als Parameter);
        ``seq`` = Zaehlerstand - (Anzahl - Index)."""
        params = []
        n = len(events)
        for i, e in enumerate(events, start=1):
            params += [e.id, e.task_id, e.field_name, self._enc(e.old_value), self._enc(e.new_value),
                       e.origin, e.actor_id, n - i, e.created_at]
        return " UNION ALL ".join([self._EVENT_ROW] * n), params

    @_transactional
    def update_task(self, task: Task, events=(), comment: TaskComment | None = None) -> bool:
        events = list(events)
        if not events:
            if comment is not None:
                raise ValueError("Ein Kommentar zur Aenderung braucht mindestens einen Verlaufseintrag.")
            return super().update_task(task)
        rows, params = self._event_rows(events)
        head = (*self._task_params(task), *self._review_params(task), task.id, task.version)
        if comment is None:
            sql = self._UPDATE_WITH_EVENTS + rows  # nosec B608 - nur feste SQL-Texte, Werte als Platzhalter
            result = self._execute(sql, (*head, len(events) + 1, *params))
        else:
            n = len(events)
            sql = self._UPDATE_WITH_COMMENT + rows  # nosec B608 - nur feste SQL-Texte, Werte als Platzhalter
            result = self._execute(sql, (*head, n + 2, comment.id, comment.task_id, self._enc(comment.body),
                                         comment.origin, comment.actor_id, self._enc(comment.author_name), n,
                                         comment.created_at, comment.updated_at, *params))
        if result.rowcount == len(events):
            task.version += 1
            return True
        return False

    @_transactional
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
