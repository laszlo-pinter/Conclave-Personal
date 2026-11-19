# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Laszlo Pinter

"""Board-Repository fuer SQLite; die Postgres-Variante erbt und tauscht nur die Ausfuehrung.

- Ticket-Nummern: Zaehler-Zeile je Projekt (``board_counters``) plus
  ``UNIQUE(project_id, number)``. Unter SQLite laufen Zaehler-``UPDATE`` und
  ``INSERT`` in einer Transaktion, die die Verbindung mit ``BEGIN IMMEDIATE`` startet
  (``isolation_level="IMMEDIATE"`` in ``sqlite/connection.py``).
- Jeder Schreibvorgang laeuft in ``_tx()``: Commit bei Erfolg, Rollback bei einer
  Ausnahme. Sonst hielte eine halbe Transaktion den Schreib-Lock und wuerde mit dem
  naechsten Schreibzugriff desselben Threads festgeschrieben.
- Loeschen ist eine Anweisung; Kommentare, Verlauf, Tickets und Zaehler haengen per
  ``ON DELETE CASCADE`` daran (Fremdschluessel sind unter SQLite eingeschaltet). Ein
  geloeschtes Ticket hinterlaesst einen Eintrag im Projekt-Verlauf, geloeschte Kommentare
  bleiben als Zeile mit ``deleted_at`` (Inhalt im Verlauf), R9.
- Freitext (Projektname, Titel, Beschreibung, Tags, Kommentare, Verlaufswerte) wird
  wie Nachrichten verschluesselt, wenn ein CryptoService gesetzt ist.
- Jede aendernde Schreiboperation erhoeht den Aenderungszaehler (``board_meta``).
  Kommentare und Verlaufseintraege bekommen dessen neuen Wert als ``seq``: eine
  eindeutige, steigende Reihenfolge, auch wenn mehrere im selben Moment entstehen.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime

from conclave_board.domain.board import POSITION_STEP, Initiative, Project, ProjectEvent, Task, TaskComment, TaskEvent

MIN_SQLITE = (3, 35)       # UPDATE ... RETURNING

_TASK_COLUMNS = ("t.id, t.project_id, p.slug, t.number, t.title, t.description, t.tags, t.status, t.position, "
                 "t.human, t.assignee, t.created_at, t.updated_at, t.version, t.rank, t.origin, t.actor_id, "
                 "t.created_by, t.review_state, t.review_at, t.review_red_count, t.review_blocking, "
                 "t.review_suggestions, t.review_checked, t.kind, t.control, t.control_scope, t.control_ack_by, "
                 "t.control_ack_at, t.initiative_id, i.slug, t.initiative_number, i.rank")
# Vorhaben (P2) gehoert zu jeder Ticket-Abfrage dazu, als LEFT JOIN (Tickets ohne Vorhaben)
_TASK_FROM = ("board_tasks t JOIN board_projects p ON p.id = t.project_id "
              "LEFT JOIN board_initiatives i ON i.id = t.initiative_id")
_UPDATE_TASK = ("UPDATE board_tasks SET title = ?, description = ?, tags = ?, status = ?, position = ?, rank = ?, "
                "human = ?, assignee = ?, updated_at = ?, review_state = ?, review_at = ?, review_red_count = ?, "
                "review_blocking = ?, review_suggestions = ?, review_checked = ?, control_ack_by = ?, "
                "control_ack_at = ?, version = version + 1 "
                "WHERE id = ? AND version = ?")
_INSERT_TASK = ("INSERT INTO board_tasks (id, project_id, number, title, description, tags, status, position, "
                "rank, human, assignee, updated_at, created_at, origin, actor_id, created_by, kind, control, "
                "control_scope, initiative_id, initiative_number) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
_INITIATIVE_COLUMNS = "i.id, i.project_id, p.slug, i.slug, i.title, i.rank, i.created_at"


class _NotInserted(Exception):
    """Kommentar nicht geschrieben (Ticket fehlt oder ist markiert); rollt den Zaehler zurueck."""


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
        self._local = threading.local()           # Tiefe verschachtelter Transaktionen je Thread

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

    def add_comment_checked(self, comment: TaskComment, *, only_if_not_human: bool = False) -> bool:
        try:
            return self.add_comment(comment, only_if_not_human=only_if_not_human)
        except _NotInserted:
            return False

    @contextmanager
    def _tx(self):
        """Ein Schreibvorgang: Commit bei Erfolg, Rollback bei Ausnahme (nur mit autocommit).

        Verschachtelt (z. B. in ``locked_task``) schliesst er sich der aeusseren Transaktion an;
        Commit oder Rollback macht nur die aeusserste."""
        depth = getattr(self._local, "depth", 0)
        self._local.depth = depth + 1
        try:
            yield
        except BaseException:
            if depth == 0 and self._autocommit:
                self._connection.rollback()
            raise
        finally:
            self._local.depth = depth
        if depth == 0 and self._autocommit:
            self._connection.commit()

    @contextmanager
    def locked_key(self, key: str):
        """Transaktion unter einer benannten Sperre (T5), z. B. je Zustaendigem.

        SQLite sperrt die ganze Datenbank (``BEGIN IMMEDIATE``); das schliesst jeden Schluessel ein."""
        with self._tx():
            if self._autocommit and not self._connection.in_transaction:
                self._connection.execute("BEGIN IMMEDIATE")
            yield

    def change_token_for(self, project_slugs: list[str], actor_id: str | None = None) -> int:
        """Aenderungszaehler nur ueber diese Projekte: hoechste Folgenummer ihrer Eintraege (T5).

        Dazu kommen Steuertickets, die ueber Projektgrenzen gelten (``all``, bei ``mine`` die des
        eigenen Menschen): Wer sie sieht, soll auch merken, wenn sie entstehen oder enden."""
        marks = ", ".join("?" for _ in project_slugs) or "NULL"
        params = tuple(project_slugs)
        queries = [
            (f"SELECT MAX(e.seq) FROM board_events e JOIN board_tasks t ON t.id = e.task_id "      # nosec B608
             f"JOIN board_projects p ON p.id = t.project_id WHERE p.slug IN ({marks})", params),
            (f"SELECT MAX(c.seq) FROM board_comments c JOIN board_tasks t ON t.id = c.task_id "    # nosec B608
             f"JOIN board_projects p ON p.id = t.project_id WHERE p.slug IN ({marks})", params),
            (f"SELECT MAX(e.seq) FROM board_project_events e JOIN board_projects p ON p.id = e.project_id "  # nosec B608
             f"WHERE p.slug IN ({marks})", params),
            ("SELECT MAX(e.seq) FROM board_events e JOIN board_tasks t ON t.id = e.task_id "
             "WHERE t.kind = 'control' AND (t.control_scope = 'all' OR (t.control_scope = 'mine' AND t.actor_id = ?))",
             (actor_id,)),
        ]
        values = [self._one(q, p)[0] for q, p in queries]
        return int(max((v for v in values if v is not None), default=0))

    def status_since_many(self, task_ids: list[str]) -> dict[str, datetime]:
        """Letzter Statuswechsel je Ticket in einer Abfrage (T5, haengende Tickets)."""
        if not task_ids:
            return {}
        marks = ", ".join("?" for _ in task_ids)
        rows = self._all(f"SELECT task_id, MAX(created_at) FROM board_events WHERE field = 'status' "  # nosec B608
                         f"AND task_id IN ({marks}) GROUP BY task_id", tuple(task_ids))
        return {row[0]: _ts(row[1]) for row in rows}

    @contextmanager
    def locked_task(self, task_id: str):
        """Transaktion, in der niemand sonst schreibt; ``True``, wenn das Ticket existiert.

        SQLite sperrt die ganze Datenbank (``BEGIN IMMEDIATE``), das schliesst die Zeile ein.
        Gegenstueck zu ``SELECT ... FOR UPDATE`` unter PostgreSQL (T2)."""
        with self._tx():
            if self._autocommit and not self._connection.in_transaction:
                self._connection.execute("BEGIN IMMEDIATE")
            row = self._one("SELECT id FROM board_tasks WHERE id = ?", (task_id,))
            yield row is not None

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

    def _bump(self) -> int:
        row = self._one("UPDATE board_meta SET value = value + 1 WHERE key = 'changes' RETURNING value")
        return int(row[0])

    def change_token(self) -> int:
        row = self._one("SELECT value FROM board_meta WHERE key = 'changes'")
        return int(row[0]) if row else 0

    # ── Projekte ─────────────────────────────────────────────────────────

    def _project(self, row) -> Project:
        return Project(id=row[0], slug=row[1], name=self._dec(row[2]), created_at=_ts(row[3]))

    def create_project(self, project: Project, event: ProjectEvent | None = None) -> None:
        with self._tx():
            self._execute("INSERT INTO board_projects (id, slug, name, created_at) VALUES (?, ?, ?, ?)",
                          (project.id, project.slug, self._enc(project.name), self._dt(project.created_at)))
            self._execute("INSERT INTO board_counters (project_id, next_number) VALUES (?, 1)", (project.id,))
            self._bump()
            if event is not None:
                self._insert_project_event(event)

    def get_project(self, slug: str) -> Project | None:
        row = self._one("SELECT id, slug, name, created_at FROM board_projects WHERE slug = ?", (slug,))
        return self._project(row) if row else None

    def list_projects(self) -> list[Project]:
        return [self._project(r) for r in self._all(
            "SELECT id, slug, name, created_at FROM board_projects ORDER BY slug")]

    def rename_project(self, slug: str, name: str, event: ProjectEvent | None = None) -> bool:
        with self._tx():
            changed = self._rowcount("UPDATE board_projects SET name = ? WHERE slug = ?",
                                     (self._enc(name), slug))
            if changed:
                self._bump()
                if event is not None:
                    self._insert_project_event(event)
        return changed == 1

    def delete_project(self, slug: str, only_empty: bool = False) -> bool:
        """Eine Anweisung; Zaehler, Tickets, Kommentare und Verlauf folgen per CASCADE.

        Mit ``only_empty`` prueft dieselbe Anweisung, dass es keine Tickets (auch keine erledigten oder
        Steuertickets) und keine Vorhaben gibt: Was ein Agent kurz vorher anlegt, geht so nicht verloren (U4).
        """
        sql = "DELETE FROM board_projects WHERE slug = ?"
        if only_empty:
            sql += (" AND NOT EXISTS (SELECT 1 FROM board_tasks WHERE board_tasks.project_id = board_projects.id)"
                    " AND NOT EXISTS (SELECT 1 FROM board_initiatives"
                    " WHERE board_initiatives.project_id = board_projects.id)")
        with self._tx():
            changed = self._rowcount(sql, (slug,))
            if changed:
                self._bump()
        return changed == 1

    # ── Tickets ──────────────────────────────────────────────────────────

    def _task(self, row) -> Task:
        tags = self._dec(row[6])
        return Task(id=row[0], project_id=row[1], project_slug=row[2], number=row[3], title=self._dec(row[4]),
                    description=self._dec(row[5]) or "", tags=tuple(json.loads(tags)) if tags else (),
                    status=row[7], position=float(row[8]), human=bool(row[9]), assignee=row[10],
                    created_at=_ts(row[11]), updated_at=_ts(row[12]), version=int(row[13]), rank=float(row[14]),
                    origin=row[15], actor_id=row[16], created_by=row[17] or "",
                    review_state=row[18] or "none", review_at=_ts(row[19]), review_red_count=int(row[20] or 0),
                    review_blocking=row[21], review_suggestions=row[22], review_checked=row[23] or "",
                    kind=row[24] or "task", control=row[25], control_scope=row[26] or "",
                    control_ack_by=row[27] or "", control_ack_at=_ts(row[28]),
                    initiative_id=row[29], initiative_slug=row[30], initiative_number=row[31],
                    initiative_rank=float(row[32]) if row[32] is not None else None)

    def _task_params(self, task: Task) -> tuple:
        return (self._enc(task.title), self._enc(task.description), self._enc(json.dumps(list(task.tags))),
                task.status, task.position, task.rank, self._bool(task.human), task.assignee,
                self._dt(task.updated_at))

    def _review_params(self, task: Task) -> tuple:
        return (task.review_state, self._dt(task.review_at), task.review_red_count, task.review_blocking,
                task.review_suggestions, task.review_checked or "", task.control_ack_by or "",
                self._dt(task.control_ack_at))

    def _origin_params(self, task: Task) -> tuple:
        return (self._dt(task.created_at), task.origin, task.actor_id, task.created_by or "", task.kind or "task",
                task.control, task.control_scope or "")

    def _next_initiative_number(self, initiative_id: str) -> int:
        """Naechste Nummer im Vorhaben (Zaehler im Vorhaben, in der laufenden Transaktion)."""
        row = self._one("UPDATE board_initiatives SET next_number = next_number + 1 WHERE id = ? "
                        "RETURNING next_number - 1", (initiative_id,))
        if row is None:
            raise ValueError("Unbekanntes Vorhaben")
        return int(row[0])

    def create_task(self, task: Task, event: TaskEvent | None = None) -> Task:
        """Legt das Ticket an und vergibt die naechste Nummer des Projekts; mit dem Ereignis
        ``created`` in derselben Transaktion."""
        with self._tx():
            row = self._one("UPDATE board_counters SET next_number = next_number + 1 WHERE project_id = ? "
                            "RETURNING next_number - 1", (task.project_id,))
            if row is None:
                raise ValueError("Unbekanntes Projekt")
            number = int(row[0])
            initiative_number = (self._next_initiative_number(task.initiative_id)
                                 if task.initiative_id else None)
            self._execute(_INSERT_TASK, (task.id, task.project_id, number, *self._task_params(task),
                                         *self._origin_params(task), task.initiative_id, initiative_number))
            self._bump()
            if event is not None:
                self._insert_event(event)
        task.number = number
        task.initiative_number = initiative_number
        return task

    def import_task(self, task: Task, comments=(), event: TaskEvent | None = None) -> bool:
        """Uebernimmt ein Ticket mit vorgegebener Nummer samt Kommentaren (Import, atomar);
        der Zaehler des Projekts springt mit. ``False``, wenn die Nummer inzwischen vergeben ist."""
        try:
            with self._tx():
                inserted = self._rowcount(
                    _INSERT_TASK + " ON CONFLICT (project_id, number) DO NOTHING",
                    (task.id, task.project_id, task.number, *self._task_params(task), *self._origin_params(task),
                     None, None))
                if inserted != 1:
                    raise _NotInserted()
                self._execute("UPDATE board_counters SET next_number = MAX(next_number, ?) WHERE project_id = ?",
                              (task.number + 1, task.project_id))
                self._bump()
                for comment in comments:
                    seq = self._bump()
                    self._execute(
                        "INSERT INTO board_comments (id, task_id, body, origin, actor_id, author_name, seq, "
                        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (comment.id, comment.task_id, self._enc(comment.body), comment.origin, comment.actor_id,
                         self._enc(comment.author_name), seq, self._dt(comment.created_at),
                         self._dt(comment.updated_at)))
                if event is not None:
                    self._insert_event(event)
        except _NotInserted:
            return False
        return True

    def get_task(self, slug: str, number: int) -> Task | None:
        row = self._one(f"SELECT {_TASK_COLUMNS} FROM {_TASK_FROM} "  # nosec B608
                        "WHERE p.slug = ? AND t.number = ?", (slug, number))
        return self._task(row) if row else None

    def get_task_by_initiative(self, slug: str, initiative: str, number: int) -> Task | None:
        row = self._one(f"SELECT {_TASK_COLUMNS} FROM {_TASK_FROM} "  # nosec B608
                        "WHERE p.slug = ? AND i.slug = ? AND t.initiative_number = ?", (slug, initiative, number))
        return self._task(row) if row else None

    # ── Vorhaben (P2) ────────────────────────────────────────────────────

    def _initiative(self, row) -> Initiative:
        return Initiative(id=row[0], project_id=row[1], project_slug=row[2], slug=row[3], title=self._dec(row[4]),
                          rank=float(row[5]), created_at=_ts(row[6]))

    def create_initiative(self, initiative: Initiative, event: ProjectEvent | None = None) -> None:
        with self._tx():
            self._execute("INSERT INTO board_initiatives (id, project_id, slug, title, rank, next_number, created_at) "
                          "VALUES (?, ?, ?, ?, ?, 1, ?)",
                          (initiative.id, initiative.project_id, initiative.slug, self._enc(initiative.title),
                           initiative.rank, self._dt(initiative.created_at)))
            self._bump()
            if event is not None:
                self._insert_project_event(event)

    def get_initiative(self, project_slug: str, slug: str) -> Initiative | None:
        row = self._one(f"SELECT {_INITIATIVE_COLUMNS} FROM board_initiatives i "  # nosec B608
                        "JOIN board_projects p ON p.id = i.project_id WHERE p.slug = ? AND i.slug = ?",
                        (project_slug, slug))
        return self._initiative(row) if row else None

    def list_initiatives(self, project_slug: str) -> list[Initiative]:
        return [self._initiative(r) for r in self._all(
            f"SELECT {_INITIATIVE_COLUMNS} FROM board_initiatives i "  # nosec B608
            "JOIN board_projects p ON p.id = i.project_id WHERE p.slug = ? ORDER BY i.rank, i.slug",
            (project_slug,))]

    def update_initiative(self, initiative: Initiative, events=()) -> None:
        with self._tx():
            self._execute("UPDATE board_initiatives SET title = ?, rank = ? WHERE id = ?",
                          (self._enc(initiative.title), initiative.rank, initiative.id))
            self._bump()
            for event in events:
                self._insert_project_event(event)

    def assign_initiative(self, task: Task, initiative: Initiative | None, event: TaskEvent) -> bool:
        """Ordnet das Ticket einem Vorhaben zu (naechste Nummer dort) oder keinem; mit Verlauf,
        dessen neuer Wert die vergebene Referenz ist. ``False``, wenn das Ticket inzwischen eine
        andere Version hat (nichts geaendert)."""
        initiative_id = initiative.id if initiative else None
        try:
            with self._tx():                       # Zaehler und Zuordnung zusammen; sonst Rollback
                number = self._next_initiative_number(initiative_id) if initiative_id else None
                if initiative is not None:
                    event.new_value = f"{task.project_slug}/{initiative.slug}-{number}"
                changed = self._rowcount(
                    "UPDATE board_tasks SET initiative_id = ?, initiative_number = ?, updated_at = ?, "
                    "version = version + 1 WHERE id = ? AND version = ?",
                    (initiative_id, number, self._dt(task.updated_at), task.id, task.version))
                if changed != 1:
                    raise _NotInserted()
                self._bump()
                self._insert_event(event)
        except _NotInserted:
            return False
        return True

    def get_task_by_id(self, task_id: str) -> Task | None:
        row = self._one(f"SELECT {_TASK_COLUMNS} FROM {_TASK_FROM} "  # nosec B608
                        "WHERE t.id = ?", (task_id,))
        return self._task(row) if row else None

    def list_tasks(self, slug: str | None = None, statuses=None, kind: str | None = None) -> list[Task]:
        """Sortiert nach Projekt, Status (alphabetisch) und Position; die Reihenfolge der
        Spalten legt der Dienst fest, nicht das Repository. ``kind`` filtert z. B. die
        Steuertickets (P6) in SQL statt im Dienst."""
        sql = f"SELECT {_TASK_COLUMNS} FROM {_TASK_FROM}"  # nosec B608
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
        if kind is not None:
            where.append("t.kind = ?")
            params.append(kind)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY p.slug, t.status, t.position, t.number"
        return [self._task(r) for r in self._all(sql, tuple(params))]

    def update_task(self, task: Task, events=(), comment: TaskComment | None = None) -> bool:
        """Ticket, zugehoerige Verlaufseintraege und optional ein Kommentar zusammen (atomar;
        der Kommentar ist das Ergebnis eines Reviews, P3).

        Optimistisch: geschrieben wird nur, wenn ``task.version`` noch die gespeicherte
        Version ist; sonst ``False`` (inzwischen geaendert oder geloescht). Bei Erfolg
        steigt ``task.version``.
        """
        with self._tx():
            changed = self._rowcount(_UPDATE_TASK, (*self._task_params(task), *self._review_params(task), task.id,
                                                    task.version))
            if changed:
                self._bump()
                for event in events:
                    self._insert_event(event)
                if comment is not None:
                    self._insert_comment(comment)
        if changed == 1:
            task.version += 1
        return changed == 1

    def claim_task(self, task_id: str, from_status: str, to_status: str, position: float, updated_at,
                   event: TaskEvent | None = None) -> bool:
        """Atomar: nur wenn das Ticket noch in ``from_status`` steht und nicht "nur fuer Menschen"
        markiert ist (fuer next_task); mit Verlaufseintrag."""
        with self._tx():
            changed = self._rowcount(
                "UPDATE board_tasks SET status = ?, position = ?, updated_at = ?, version = version + 1 "
                "WHERE id = ? AND status = ? AND human = ?",
                (to_status, position, self._dt(updated_at), task_id, from_status, self._bool(False)))
            if changed:
                self._bump()
                if event is not None:
                    self._insert_event(event)
        return changed == 1

    def delete_task(self, task_id: str, tombstone: ProjectEvent | None = None) -> bool:
        """Kommentare und Verlauf folgen per CASCADE; ``tombstone`` bleibt im Projekt-Verlauf."""
        with self._tx():
            changed = self._rowcount("DELETE FROM board_tasks WHERE id = ?", (task_id,))
            if changed:
                self._bump()
                if tombstone is not None:
                    self._insert_project_event(tombstone)
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
        Die Version steigt mit, damit ein vorher gelesener Stand nicht zurueckgeschrieben wird.
        """
        with self._tx():
            self._bump()
            for index, (task_id, _pos) in enumerate(self.column_positions(project_id, status), start=1):
                self._execute("UPDATE board_tasks SET position = ?, version = version + 1 WHERE id = ?",
                              (index * POSITION_STEP, task_id))

    # ── Prioritaet (P1) ──────────────────────────────────────────────────

    def max_rank(self, project_id: str) -> float:
        row = self._one("SELECT MAX(rank) FROM board_tasks WHERE project_id = ?", (project_id,))
        return float(row[0]) if row and row[0] is not None else 0.0

    def renumber_ranks(self, project_id: str) -> None:
        """Raenge des Projekts auf gleichmaessige Abstaende setzen, Reihenfolge bleibt (wie renumber_column).

        Die Version steigt mit: Ein Agent, der das Ticket vorher gelesen hat, kann sonst beim
        Schreiben einen alten Rang zurueckschreiben, ohne 409 und ohne Verlauf (P1-Review)."""
        with self._tx():
            self._bump()
            rows = self._all("SELECT id FROM board_tasks WHERE project_id = ? ORDER BY rank, number", (project_id,))
            for index, (task_id,) in enumerate(rows, start=1):
                self._execute("UPDATE board_tasks SET rank = ?, version = version + 1 WHERE id = ?",
                              (index * POSITION_STEP, task_id))

    # ── Kommentare ───────────────────────────────────────────────────────

    def _comment(self, row) -> TaskComment:
        return TaskComment(id=row[0], task_id=row[1], body=self._dec(row[2]), origin=row[3], actor_id=row[4],
                           author_name=self._dec(row[5]) or "", created_at=_ts(row[6]), updated_at=_ts(row[7]))

    def add_comment(self, comment: TaskComment, *, only_if_not_human: bool = False) -> bool:
        """Mit ``only_if_not_human`` nur, wenn das Ticket beim Schreiben nicht "nur fuer Menschen" ist."""
        with self._tx():
            seq = self._bump()
            inserted = self._rowcount(
                "INSERT INTO board_comments (id, task_id, body, origin, actor_id, author_name, seq, created_at, "
                "updated_at) SELECT ?, ?, ?, ?, ?, ?, ?, ?, ? "
                "WHERE EXISTS (SELECT 1 FROM board_tasks WHERE id = ? AND (human = ? OR ?))",
                (comment.id, comment.task_id, self._enc(comment.body), comment.origin, comment.actor_id,
                 self._enc(comment.author_name), seq, self._dt(comment.created_at), self._dt(comment.updated_at),
                 comment.task_id, self._bool(False), self._bool(not only_if_not_human)))
            if inserted != 1:
                raise _NotInserted()
        return True

    def _insert_comment(self, comment: TaskComment) -> None:
        seq = self._bump()
        self._execute(
            "INSERT INTO board_comments (id, task_id, body, origin, actor_id, author_name, seq, created_at, "
            "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (comment.id, comment.task_id, self._enc(comment.body), comment.origin, comment.actor_id,
             self._enc(comment.author_name), seq, self._dt(comment.created_at), self._dt(comment.updated_at)))

    def last_comment(self, task_id: str, origin: str) -> TaskComment | None:
        """Juengster sichtbarer Kommentar dieser Herkunft (z. B. das letzte Review)."""
        row = self._one("SELECT id, task_id, body, origin, actor_id, author_name, created_at, updated_at "
                        "FROM board_comments WHERE task_id = ? AND origin = ? AND deleted_at IS NULL "
                        "ORDER BY seq DESC LIMIT 1", (task_id, origin))
        return self._comment(row) if row else None

    def get_comment(self, comment_id: str) -> TaskComment | None:
        row = self._one("SELECT id, task_id, body, origin, actor_id, author_name, created_at, updated_at "
                        "FROM board_comments WHERE id = ? AND deleted_at IS NULL", (comment_id,))
        return self._comment(row) if row else None

    def list_comments(self, task_id: str) -> list[TaskComment]:
        return [self._comment(r) for r in self._all(
            "SELECT id, task_id, body, origin, actor_id, author_name, created_at, updated_at "
            "FROM board_comments WHERE task_id = ? AND deleted_at IS NULL ORDER BY seq", (task_id,))]

    def update_comment(self, comment: TaskComment, event: TaskEvent | None = None) -> bool:
        with self._tx():
            changed = self._rowcount(
                "UPDATE board_comments SET body = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
                (self._enc(comment.body), self._dt(comment.updated_at), comment.id))
            if changed:
                self._bump()
                if event is not None:
                    self._insert_event(event)
        return changed == 1

    def delete_comment(self, comment_id: str, deleted_at=None, event: TaskEvent | None = None) -> bool:
        """Soft-Delete: die Zeile bleibt mit ``deleted_at``, der Inhalt steht im Verlauf (R9)."""
        with self._tx():
            changed = self._rowcount(
                "UPDATE board_comments SET body = '', deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
                (self._dt(deleted_at or datetime.now().astimezone()), comment_id))
            if changed:
                self._bump()
                if event is not None:
                    self._insert_event(event)
        return changed == 1

    # ── Verlauf ──────────────────────────────────────────────────────────

    def add_event(self, event: TaskEvent) -> None:
        with self._tx():
            self._insert_event(event)

    def _insert_event(self, event: TaskEvent) -> None:
        """Innerhalb einer laufenden Transaktion; ``seq`` ist der neue Zaehlerstand."""
        seq = self._bump()
        self._execute(
            "INSERT INTO board_events (id, task_id, field, old_value, new_value, origin, actor_id, seq, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (event.id, event.task_id, event.field_name, self._enc(event.old_value), self._enc(event.new_value),
             event.origin, event.actor_id, seq, self._dt(event.created_at)))

    def list_events(self, task_id: str) -> list[TaskEvent]:
        return [TaskEvent(id=r[0], task_id=r[1], field_name=r[2], old_value=self._dec(r[3]),
                          new_value=self._dec(r[4]), origin=r[5], actor_id=r[6], created_at=_ts(r[7]))
                for r in self._all("SELECT id, task_id, field, old_value, new_value, origin, actor_id, created_at "
                                   "FROM board_events WHERE task_id = ? ORDER BY seq", (task_id,))]

    # ── Projekt-Verlauf (R9) ─────────────────────────────────────────────

    def _insert_project_event(self, event: ProjectEvent) -> None:
        seq = self._bump()
        self._execute(
            "INSERT INTO board_project_events (id, project_id, field, old_value, new_value, origin, actor_id, seq, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (event.id, event.project_id, event.field_name, self._enc(event.old_value), self._enc(event.new_value),
             event.origin, event.actor_id, seq, self._dt(event.created_at)))

    def list_project_events(self, project_id: str) -> list[ProjectEvent]:
        return [ProjectEvent(id=r[0], project_id=r[1], field_name=r[2], old_value=self._dec(r[3]),
                             new_value=self._dec(r[4]), origin=r[5], actor_id=r[6], created_at=_ts(r[7]))
                for r in self._all("SELECT id, project_id, field, old_value, new_value, origin, actor_id, created_at "
                                   "FROM board_project_events WHERE project_id = ? ORDER BY seq", (project_id,))]

    # ── Einstellungen (R9: zuletzt bekannte letzte Spalte) ───────────────

    def get_setting(self, key: str) -> str | None:
        row = self._one("SELECT value FROM board_settings WHERE key = ?", (key,))
        return row[0] if row else None

    def set_setting(self, key: str, value: str) -> None:
        with self._tx():
            self._execute("INSERT INTO board_settings (key, value) VALUES (?, ?) "
                          "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (key, value))
