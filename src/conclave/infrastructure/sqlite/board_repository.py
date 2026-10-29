"""Board-Repository fuer SQLite; die Postgres-Variante erbt und tauscht nur die Ausfuehrung.

- Ticket-Nummern: Zaehler-Zeile je Projekt (``board_counters``) plus
  ``UNIQUE(project_id, number)``. Unter SQLite laufen Zaehler-``UPDATE`` und
  ``INSERT`` in einer Transaktion, die die Verbindung mit ``BEGIN IMMEDIATE`` startet
  (``isolation_level="IMMEDIATE"`` in ``sqlite/connection.py``).
- Jeder Schreibvorgang laeuft in ``_tx()``: Commit bei Erfolg, Rollback bei einer
  Ausnahme. Sonst hielte eine halbe Transaktion den Schreib-Lock und wuerde mit dem
  naechsten Schreibzugriff desselben Threads festgeschrieben.
- Loeschen ist eine Anweisung; Kommentare, Verlauf, Tickets und Zaehler haengen per
  ``ON DELETE CASCADE`` daran (Fremdschluessel sind unter SQLite eingeschaltet).
- Freitext (Projektname, Titel, Beschreibung, Tags, Kommentare, Verlaufswerte) wird
  wie Nachrichten verschluesselt, wenn ein CryptoService gesetzt ist.
- Jede aendernde Schreiboperation erhoeht den Aenderungszaehler (``board_meta``).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from conclave.domain.board import Project, Task, TaskComment, TaskEvent

POSITION_STEP = 1024.0
MIN_SQLITE = (3, 35)       # UPDATE ... RETURNING

_TASK_COLUMNS = ("t.id, t.project_id, p.slug, t.number, t.title, t.description, t.tags, t.status, t.position, "
                 "t.human, t.assignee, t.created_at, t.updated_at")


def _ts(value):
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


class SQLiteBoardRepository:
    placeholder = "?"

    def __init__(self, connection, crypto=None, *, autocommit: bool = False):
        if self.placeholder == "?" and sqlite3.sqlite_version_info < MIN_SQLITE:
            raise RuntimeError(f"Das Board braucht SQLite >= {'.'.join(map(str, MIN_SQLITE))} "
                               f"(gefunden: {sqlite3.sqlite_version})")
        self._connection = connection
        self._crypto = crypto
        self._autocommit = autocommit

    # ── Ausfuehrung (Postgres ueberschreibt) ─────────────────────────────

    def _sql(self, sql: str) -> str:
        return sql if self.placeholder == "?" else sql.replace("?", self.placeholder)

    def _execute(self, sql: str, params: tuple = ()):
        return self._connection.execute(self._sql(sql), params)

    def _all(self, sql: str, params: tuple = ()) -> list:
        return self._execute(sql, params).fetchall()

    def _one(self, sql: str, params: tuple = ()):
        return self._execute(sql, params).fetchone()

    def _rowcount(self, sql: str, params: tuple = ()) -> int:
        return self._execute(sql, params).rowcount

    @contextmanager
    def _tx(self):
        """Ein Schreibvorgang: Commit bei Erfolg, Rollback bei Ausnahme (nur mit autocommit)."""
        try:
            yield
        except BaseException:
            if self._autocommit:
                self._connection.rollback()
            raise
        if self._autocommit:
            self._connection.commit()

    def _dt(self, value):
        return value.isoformat() if value is not None else None

    def _bool(self, value) -> int | bool:
        return int(bool(value))

    # ── Verschluesselung ─────────────────────────────────────────────────

    def _enc(self, text: str | None) -> str | None:
        if text is None or self._crypto is None:
            return text
        return self._crypto.encrypt(text)

    def _dec(self, text: str | None) -> str | None:
        if text is None or self._crypto is None:
            return text
        return self._crypto.decrypt(text)

    # ── Aenderungszaehler ────────────────────────────────────────────────

    def _bump(self) -> None:
        self._execute("UPDATE board_meta SET value = value + 1 WHERE key = 'changes'")

    def change_token(self) -> int:
        row = self._one("SELECT value FROM board_meta WHERE key = 'changes'")
        return int(row[0]) if row else 0

    # ── Projekte ─────────────────────────────────────────────────────────

    def _project(self, row) -> Project:
        return Project(id=row[0], slug=row[1], name=self._dec(row[2]), created_at=_ts(row[3]))

    def create_project(self, project: Project) -> None:
        with self._tx():
            self._execute("INSERT INTO board_projects (id, slug, name, created_at) VALUES (?, ?, ?, ?)",
                          (project.id, project.slug, self._enc(project.name), self._dt(project.created_at)))
            self._execute("INSERT INTO board_counters (project_id, next_number) VALUES (?, 1)", (project.id,))
            self._bump()

    def get_project(self, slug: str) -> Project | None:
        row = self._one("SELECT id, slug, name, created_at FROM board_projects WHERE slug = ?", (slug,))
        return self._project(row) if row else None

    def list_projects(self) -> list[Project]:
        return [self._project(r) for r in self._all(
            "SELECT id, slug, name, created_at FROM board_projects ORDER BY slug")]

    def rename_project(self, slug: str, name: str) -> bool:
        with self._tx():
            changed = self._rowcount("UPDATE board_projects SET name = ? WHERE slug = ?",
                                     (self._enc(name), slug))
            if changed:
                self._bump()
        return changed == 1

    def delete_project(self, slug: str) -> bool:
        """Eine Anweisung; Zaehler, Tickets, Kommentare und Verlauf folgen per CASCADE."""
        with self._tx():
            changed = self._rowcount("DELETE FROM board_projects WHERE slug = ?", (slug,))
            if changed:
                self._bump()
        return changed == 1

    # ── Tickets ──────────────────────────────────────────────────────────

    def _task(self, row) -> Task:
        tags = self._dec(row[6])
        return Task(id=row[0], project_id=row[1], project_slug=row[2], number=row[3], title=self._dec(row[4]),
                    description=self._dec(row[5]) or "", tags=tuple(json.loads(tags)) if tags else (),
                    status=row[7], position=float(row[8]), human=bool(row[9]), assignee=row[10],
                    created_at=_ts(row[11]), updated_at=_ts(row[12]))

    def _task_params(self, task: Task) -> tuple:
        return (self._enc(task.title), self._enc(task.description), self._enc(json.dumps(list(task.tags))),
                task.status, task.position, self._bool(task.human), task.assignee, self._dt(task.updated_at))

    def create_task(self, task: Task) -> Task:
        """Legt das Ticket an und vergibt die naechste Nummer des Projekts."""
        with self._tx():
            row = self._one("UPDATE board_counters SET next_number = next_number + 1 WHERE project_id = ? "
                            "RETURNING next_number - 1", (task.project_id,))
            if row is None:
                raise ValueError("Unbekanntes Projekt")
            number = int(row[0])
            self._execute(
                "INSERT INTO board_tasks (id, project_id, number, title, description, tags, status, position, "
                "human, assignee, updated_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (task.id, task.project_id, number, *self._task_params(task), self._dt(task.created_at)))
            self._bump()
        task.number = number
        return task

    def get_task(self, slug: str, number: int) -> Task | None:
        row = self._one(f"SELECT {_TASK_COLUMNS} FROM board_tasks t JOIN board_projects p ON p.id = t.project_id "  # nosec B608
                        "WHERE p.slug = ? AND t.number = ?", (slug, number))
        return self._task(row) if row else None

    def get_task_by_id(self, task_id: str) -> Task | None:
        row = self._one(f"SELECT {_TASK_COLUMNS} FROM board_tasks t JOIN board_projects p ON p.id = t.project_id "  # nosec B608
                        "WHERE t.id = ?", (task_id,))
        return self._task(row) if row else None

    def list_tasks(self, slug: str | None = None, statuses=None) -> list[Task]:
        """Sortiert nach Projekt, Status (alphabetisch) und Position; die Reihenfolge der
        Spalten legt der Dienst fest, nicht das Repository."""
        sql = f"SELECT {_TASK_COLUMNS} FROM board_tasks t JOIN board_projects p ON p.id = t.project_id"  # nosec B608
        where, params = [], []
        if slug is not None:
            where.append("p.slug = ?")
            params.append(slug)
        if statuses is not None:
            statuses = list(statuses)
            if not statuses:
                return []
            where.append("t.status IN (" + ", ".join("?" for _ in statuses) + ")")
            params.extend(statuses)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY p.slug, t.status, t.position, t.number"
        return [self._task(r) for r in self._all(sql, tuple(params))]

    def update_task(self, task: Task) -> bool:
        with self._tx():
            changed = self._rowcount(
                "UPDATE board_tasks SET title = ?, description = ?, tags = ?, status = ?, position = ?, human = ?, "
                "assignee = ?, updated_at = ? WHERE id = ?", (*self._task_params(task), task.id))
            if changed:
                self._bump()
        return changed == 1

    def claim_task(self, task_id: str, from_status: str, to_status: str, position: float, updated_at) -> bool:
        """Atomar: nur wenn das Ticket noch in ``from_status`` steht (fuer next_task)."""
        with self._tx():
            changed = self._rowcount(
                "UPDATE board_tasks SET status = ?, position = ?, updated_at = ? WHERE id = ? AND status = ?",
                (to_status, position, self._dt(updated_at), task_id, from_status))
            if changed:
                self._bump()
        return changed == 1

    def delete_task(self, task_id: str) -> bool:
        """Eine Anweisung; Kommentare und Verlauf folgen per CASCADE."""
        with self._tx():
            changed = self._rowcount("DELETE FROM board_tasks WHERE id = ?", (task_id,))
            if changed:
                self._bump()
        return changed == 1

    # ── Positionen ───────────────────────────────────────────────────────

    def column_positions(self, project_id: str, status: str) -> list[tuple[str, float]]:
        return [(r[0], float(r[1])) for r in self._all(
            "SELECT id, position FROM board_tasks WHERE project_id = ? AND status = ? ORDER BY position, number",
            (project_id, status))]

    def renumber_column(self, project_id: str, status: str) -> None:
        """Positionen der Spalte auf gleichmaessige Abstaende setzen, Reihenfolge bleibt.

        Erst den Schreib-Lock holen (Zaehler erhoehen startet die IMMEDIATE-Transaktion),
        dann lesen, damit keine gleichzeitig eingefuegte Karte fehlt. Zeile fuer Zeile,
        weil SQLite eine korrelierte Unterabfrage mit schon geaenderten Werten auswertet.
        """
        with self._tx():
            self._bump()
            for index, (task_id, _pos) in enumerate(self.column_positions(project_id, status), start=1):
                self._execute("UPDATE board_tasks SET position = ? WHERE id = ?", (index * POSITION_STEP, task_id))

    # ── Kommentare ───────────────────────────────────────────────────────

    def _comment(self, row) -> TaskComment:
        return TaskComment(id=row[0], task_id=row[1], body=self._dec(row[2]), origin=row[3], actor_id=row[4],
                           author_name=self._dec(row[5]) or "", created_at=_ts(row[6]), updated_at=_ts(row[7]))

    def add_comment(self, comment: TaskComment) -> None:
        with self._tx():
            self._execute(
                "INSERT INTO board_comments (id, task_id, body, origin, actor_id, author_name, created_at, "
                "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (comment.id, comment.task_id, self._enc(comment.body), comment.origin, comment.actor_id,
                 self._enc(comment.author_name), self._dt(comment.created_at), self._dt(comment.updated_at)))
            self._bump()

    def get_comment(self, comment_id: str) -> TaskComment | None:
        row = self._one("SELECT id, task_id, body, origin, actor_id, author_name, created_at, updated_at "
                        "FROM board_comments WHERE id = ?", (comment_id,))
        return self._comment(row) if row else None

    def list_comments(self, task_id: str) -> list[TaskComment]:
        return [self._comment(r) for r in self._all(
            "SELECT id, task_id, body, origin, actor_id, author_name, created_at, updated_at "
            "FROM board_comments WHERE task_id = ? ORDER BY created_at, id", (task_id,))]

    def update_comment(self, comment: TaskComment) -> bool:
        with self._tx():
            changed = self._rowcount("UPDATE board_comments SET body = ?, updated_at = ? WHERE id = ?",
                                     (self._enc(comment.body), self._dt(comment.updated_at), comment.id))
            if changed:
                self._bump()
        return changed == 1

    def delete_comment(self, comment_id: str) -> bool:
        with self._tx():
            changed = self._rowcount("DELETE FROM board_comments WHERE id = ?", (comment_id,))
            if changed:
                self._bump()
        return changed == 1

    # ── Verlauf ──────────────────────────────────────────────────────────

    def add_event(self, event: TaskEvent) -> None:
        with self._tx():
            self._execute(
                "INSERT INTO board_events (id, task_id, field, old_value, new_value, origin, actor_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (event.id, event.task_id, event.field_name, self._enc(event.old_value), self._enc(event.new_value),
                 event.origin, event.actor_id, self._dt(event.created_at)))
            self._bump()

    def list_events(self, task_id: str) -> list[TaskEvent]:
        return [TaskEvent(id=r[0], task_id=r[1], field_name=r[2], old_value=self._dec(r[3]),
                          new_value=self._dec(r[4]), origin=r[5], actor_id=r[6], created_at=_ts(r[7]))
                for r in self._all("SELECT id, task_id, field, old_value, new_value, origin, actor_id, created_at "
                                   "FROM board_events WHERE task_id = ? ORDER BY created_at, id", (task_id,))]
