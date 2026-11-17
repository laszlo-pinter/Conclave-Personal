# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Laszlo Pinter

"""Migrations-Runner und die Migrationsreihe des Boards.

Jede Migration hat eine ID und fuegt Spalten hinzu, fuehrt Anweisungen aus
oder ruft eine Funktion auf. Eine Tracking-Tabelle haelt fest, welche
Migrationen gelaufen sind; neue laufen beim Start automatisch.

Jede Migration laeuft in einer eigenen Transaktion und wird im selben Schritt
eingetragen. Schlaegt sie fehl, wird alles zurueckgerollt, nichts eingetragen
und der Start mit ``MigrationError`` abgebrochen. Spalten, die schon da sind
(z. B. weil das Grundschema sie anlegt), werden vorher geprueft und nicht
erneut angelegt. Unter PostgreSQL laeuft jeder Durchgang unter einer
Advisory-Sperre, damit zwei Instanzen beim Start nicht gleichzeitig migrieren.

Zwei Reihen (T1):

- **Board** (``board_migrations``): die Tabellen des Boards. Das Board-Paket
  braucht nur diese Reihe.
- **Personal** (``_migrations``, in ``conclave.infrastructure.migrations``):
  alles andere. In einer Personal-Datenbank stehen dort auch die sechs
  Board-Migrationen bis v0.7.0.

Die Board-Reihe uebernimmt bei jedem Start die Board-Migrationen bis v0.7.0
(``LEGACY_BOARD_IDS``) aus ``_migrations``, einzeln je Migration: Was dort steht,
wird in ``board_migrations`` nachgetragen, nicht erneut ausgefuehrt.
``_migrations`` bleibt unveraendert, so kann eine aeltere Version dieselbe
Datenbank weiter oeffnen. Umgekehrt ist kein Abgleich noetig: Die alten
Board-Migrationen sind wiederholbar (``IF NOT EXISTS``, Spaltenpruefung). Oeffnet
Personal eine Datenbank, die nur das Board-Paket angelegt hat, laufen sie dort
noch einmal ohne Wirkung und werden in ``_migrations`` eingetragen.
Die Reihenfolge der beiden Reihen ist beliebig: Keine Migration der einen
beruehrt Tabellen der anderen.
"""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger("conclave.migrations")

BOARD_TABLE = "board_migrations"
PERSONAL_TABLE = "_migrations"
_TABLES = frozenset({BOARD_TABLE, PERSONAL_TABLE})     # nur diese Namen landen in SQL-Texten

# Schluessel der Advisory-Sperre unter PostgreSQL (fest, fuer alle Reihen derselbe)
ADVISORY_LOCK_KEY = 0x436F6E63   # "Conc"


@dataclass(frozen=True)
class Migration:
    id: str
    description: str
    # (Tabelle, Spalte, Definition): ADD COLUMN nur, wenn die Spalte fehlt
    columns: tuple[tuple[str, str, str], ...] = ()
    statements: tuple[str, ...] = ()
    fn: Callable | None = None


class MigrationError(RuntimeError):
    """Eine Migration ist fehlgeschlagen; die Datenbank ist unveraendert, der Start bricht ab."""

    def __init__(self, migration_id: str, statement: str | None, cause: Exception):
        where = f" bei Anweisung {statement.strip()[:200]!r}" if statement else ""
        super().__init__(
            f"Migration {migration_id} fehlgeschlagen{where}: {type(cause).__name__}: {cause}. "
            "Die Migration wurde zurueckgerollt und nicht eingetragen; der Start wird abgebrochen. "
            "Datenbank-Backup und Log pruefen."
        )
        self.migration_id = migration_id


# ── Migrationsreihe des Boards ──────────────────────────────────────────

BOARD_MIGRATIONS: list[Migration] = [
    Migration(
        id="012_board",
        description="Board: Projekte, Tickets, Kommentare, Verlauf, Zaehler (Plan board.md, B1)",
        fn=lambda connection, is_postgres: _create_board_tables(connection, is_postgres),
    ),
    Migration(
        id="014_board_rank",
        description="Prioritaet je Ticket (rank), uebernommen aus der bisherigen Position (P1)",
        fn=lambda connection, is_postgres: _add_board_rank(connection, is_postgres),
    ),
    Migration(
        id="015_board_history",
        description="Herkunft der Tickets, geloeschte Kommentare, Projekt-Verlauf und Board-Einstellungen (R9)",
        fn=lambda connection, is_postgres: _add_board_history(connection, is_postgres),
    ),
    Migration(
        id="016_board_review",
        description="Review-Status je Ticket (P3)",
        fn=lambda connection, is_postgres: _add_board_review(connection, is_postgres),
    ),
    Migration(
        id="017_board_control",
        description="Steuertickets des Menschen: Pause und Hinweis (P6)",
        fn=lambda connection, is_postgres: _add_board_control(connection, is_postgres),
    ),
    Migration(
        id="020_board_initiatives",
        description="Vorhaben im Projekt mit eigener fortlaufender Nummer (P2)",
        fn=lambda connection, is_postgres: _add_board_initiatives(connection, is_postgres),
    ),
]

# Board-Migrationen, die bis v0.7.0 in der gemeinsamen Liste (``_migrations``) liefen.
# Neue Board-Migrationen kommen nur noch in ``board_migrations``.
LEGACY_BOARD_IDS = ("012_board", "014_board_rank", "015_board_history", "016_board_review",
                    "017_board_control", "020_board_initiatives")


# ── Board-Tabellen ──────────────────────────────────────────────────────

def _create_board_tables(connection, is_postgres: bool) -> None:
    ts = "TIMESTAMPTZ" if is_postgres else "TEXT"
    boolean = "BOOLEAN NOT NULL DEFAULT FALSE" if is_postgres else "INTEGER NOT NULL DEFAULT 0"
    real = "DOUBLE PRECISION" if is_postgres else "REAL"
    statements = [
        f"""CREATE TABLE IF NOT EXISTS board_projects (
            id         TEXT PRIMARY KEY,
            slug       TEXT NOT NULL UNIQUE,
            name       TEXT NOT NULL,
            created_at {ts} NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS board_counters (
            project_id  TEXT PRIMARY KEY REFERENCES board_projects(id) ON DELETE CASCADE,
            next_number INTEGER NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS board_tasks (
            id          TEXT PRIMARY KEY,
            project_id  TEXT NOT NULL REFERENCES board_projects(id) ON DELETE CASCADE,
            number      INTEGER NOT NULL,
            title       TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            tags        TEXT NOT NULL DEFAULT '[]',
            status      TEXT NOT NULL,
            position    {real} NOT NULL DEFAULT 0,
            rank        {real} NOT NULL DEFAULT 0,
            human       {boolean},
            assignee    TEXT,
            version     INTEGER NOT NULL DEFAULT 1,
            created_at  {ts} NOT NULL,
            updated_at  {ts} NOT NULL,
            origin      TEXT,
            actor_id    TEXT,
            created_by  TEXT NOT NULL DEFAULT '',
            review_state       TEXT NOT NULL DEFAULT 'none',
            review_at          {ts},
            review_red_count   INTEGER NOT NULL DEFAULT 0,
            review_blocking    INTEGER,
            review_suggestions INTEGER,
            review_checked     TEXT NOT NULL DEFAULT '',
            kind               TEXT NOT NULL DEFAULT 'task',
            control            TEXT,
            control_scope      TEXT NOT NULL DEFAULT '',
            control_ack_by     TEXT NOT NULL DEFAULT '',
            control_ack_at     {ts},
            initiative_id      TEXT,
            initiative_number  INTEGER,
            UNIQUE(project_id, number)
        )""",
        f"""CREATE TABLE IF NOT EXISTS board_comments (
            id          TEXT PRIMARY KEY,
            task_id     TEXT NOT NULL REFERENCES board_tasks(id) ON DELETE CASCADE,
            body        TEXT NOT NULL,
            origin      TEXT,
            actor_id    TEXT,
            author_name TEXT NOT NULL DEFAULT '',
            seq         INTEGER NOT NULL DEFAULT 0,
            created_at  {ts} NOT NULL,
            updated_at  {ts},
            deleted_at  {ts}
        )""",
        f"""CREATE TABLE IF NOT EXISTS board_events (
            id         TEXT PRIMARY KEY,
            task_id    TEXT NOT NULL REFERENCES board_tasks(id) ON DELETE CASCADE,
            field      TEXT NOT NULL,
            old_value  TEXT,
            new_value  TEXT,
            origin     TEXT,
            actor_id   TEXT,
            seq        INTEGER NOT NULL DEFAULT 0,
            created_at {ts} NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS board_meta (
            key   TEXT PRIMARY KEY,
            value INTEGER NOT NULL
        )""",
        *_board_history_tables(ts),
        _initiatives_table(ts, real),
        "INSERT INTO board_meta (key, value) VALUES ('changes', 0) ON CONFLICT (key) DO NOTHING",
        "CREATE INDEX IF NOT EXISTS idx_board_tasks_column ON board_tasks(project_id, status, position)",
        "CREATE INDEX IF NOT EXISTS idx_board_comments_task ON board_comments(task_id, seq)",
        "CREATE INDEX IF NOT EXISTS idx_board_events_task ON board_events(task_id, seq)",
    ]
    if is_postgres:
        with connection.cursor() as cur:
            for statement in statements:
                cur.execute(statement)
    else:
        for statement in statements:
            connection.execute(statement)


def _add_board_rank(connection, is_postgres: bool) -> None:
    if _has_column(connection, is_postgres, "board_tasks", "rank"):
        return
    real = "DOUBLE PRECISION" if is_postgres else "REAL"
    statements = (f"ALTER TABLE board_tasks ADD COLUMN rank {real} NOT NULL DEFAULT 0",
                  "UPDATE board_tasks SET rank = position")      # sichtbare Reihenfolge bleibt
    for statement in statements:
        if is_postgres:
            with connection.cursor() as cur:
                cur.execute(statement)
        else:
            connection.execute(statement)


def _board_history_tables(ts: str) -> list[str]:
    return [
        f"""CREATE TABLE IF NOT EXISTS board_project_events (
            id         TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES board_projects(id) ON DELETE CASCADE,
            field      TEXT NOT NULL,
            old_value  TEXT,
            new_value  TEXT,
            origin     TEXT,
            actor_id   TEXT,
            seq        INTEGER NOT NULL DEFAULT 0,
            created_at {ts} NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_board_project_events ON board_project_events(project_id, seq)",
        """CREATE TABLE IF NOT EXISTS board_settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )""",
    ]


def _add_board_history(connection, is_postgres: bool) -> None:
    ts = "TIMESTAMPTZ" if is_postgres else "TEXT"
    statements = []
    for column, ddl in (("origin", "TEXT"), ("actor_id", "TEXT"), ("created_by", "TEXT NOT NULL DEFAULT ''")):
        if not _has_column(connection, is_postgres, "board_tasks", column):
            statements.append(f"ALTER TABLE board_tasks ADD COLUMN {column} {ddl}")
    if not _has_column(connection, is_postgres, "board_comments", "deleted_at"):
        statements.append(f"ALTER TABLE board_comments ADD COLUMN deleted_at {ts}")
    statements += _board_history_tables(ts)
    for statement in statements:
        if is_postgres:
            with connection.cursor() as cur:
                cur.execute(statement)
        else:
            connection.execute(statement)


def _add_board_review(connection, is_postgres: bool) -> None:
    ts = "TIMESTAMPTZ" if is_postgres else "TEXT"
    columns = (("review_state", "TEXT NOT NULL DEFAULT 'none'"), ("review_at", ts),
               ("review_red_count", "INTEGER NOT NULL DEFAULT 0"), ("review_blocking", "INTEGER"),
               ("review_suggestions", "INTEGER"), ("review_checked", "TEXT NOT NULL DEFAULT ''"))
    for column, ddl in columns:
        if _has_column(connection, is_postgres, "board_tasks", column):
            continue
        statement = f"ALTER TABLE board_tasks ADD COLUMN {column} {ddl}"
        if is_postgres:
            with connection.cursor() as cur:
                cur.execute(statement)
        else:
            connection.execute(statement)


def _add_board_control(connection, is_postgres: bool) -> None:
    ts = "TIMESTAMPTZ" if is_postgres else "TEXT"
    columns = (("kind", "TEXT NOT NULL DEFAULT 'task'"), ("control", "TEXT"),
               ("control_scope", "TEXT NOT NULL DEFAULT ''"), ("control_ack_by", "TEXT NOT NULL DEFAULT ''"),
               ("control_ack_at", ts))
    statements = [f"ALTER TABLE board_tasks ADD COLUMN {column} {ddl}" for column, ddl in columns
                  if not _has_column(connection, is_postgres, "board_tasks", column)]
    # Steuertickets werden bei jeder Board-Antwort gelesen (Feld control)
    statements.append("CREATE INDEX IF NOT EXISTS idx_board_tasks_kind ON board_tasks(kind, status)")
    for statement in statements:
        if is_postgres:
            with connection.cursor() as cur:
                cur.execute(statement)
        else:
            connection.execute(statement)


def _initiatives_table(ts: str, real: str) -> str:
    return f"""CREATE TABLE IF NOT EXISTS board_initiatives (
            id          TEXT PRIMARY KEY,
            project_id  TEXT NOT NULL REFERENCES board_projects(id) ON DELETE CASCADE,
            slug        TEXT NOT NULL,
            title       TEXT NOT NULL,
            rank        {real} NOT NULL DEFAULT 0,
            next_number INTEGER NOT NULL DEFAULT 1,
            created_at  {ts} NOT NULL,
            UNIQUE(project_id, slug)
        )"""


def _add_board_initiatives(connection, is_postgres: bool) -> None:
    ts = "TIMESTAMPTZ" if is_postgres else "TEXT"
    real = "DOUBLE PRECISION" if is_postgres else "REAL"
    statements = [_initiatives_table(ts, real)]
    if not _has_column(connection, is_postgres, "board_tasks", "initiative_id"):
        # Ohne Fremdschluessel wie im Basisschema: Vorhaben werden nicht einzeln geloescht,
        # beim Loeschen des Projekts entfernt CASCADE Vorhaben und Tickets zusammen
        statements.append("ALTER TABLE board_tasks ADD COLUMN initiative_id TEXT")
    if not _has_column(connection, is_postgres, "board_tasks", "initiative_number"):
        statements.append("ALTER TABLE board_tasks ADD COLUMN initiative_number INTEGER")
    # Eine Nummer je Vorhaben nur einmal (lueckenlos wie die Projektnummer)
    statements.append("CREATE UNIQUE INDEX IF NOT EXISTS idx_board_tasks_initiative "
                      "ON board_tasks(initiative_id, initiative_number)")
    for statement in statements:
        if is_postgres:
            with connection.cursor() as cur:
                cur.execute(statement)
        else:
            connection.execute(statement)


# ── Runner ────────────────────────────────────────────────────────────────

# Erweiterungen bringen eigene Reihen mit eigener Tracking-Tabelle (T4), z. B. board_team_migrations
_EXTENSION_TABLE = re.compile(r"^[a-z][a-z0-9_]{0,40}_migrations$")


def _table(table: str) -> str:
    """Nur bekannte oder als Erweiterung gueltige Namen landen in SQL-Texten."""
    if table not in _TABLES and not _EXTENSION_TABLE.fullmatch(table):
        raise ValueError(f"Unbekannte Migrationstabelle: {table!r}")
    return table


def _run(connection, is_postgres: bool, statement: str, params: tuple = ()):
    if is_postgres:
        with connection.cursor() as cur:
            cur.execute(statement.replace("?", "%s"), params)
            return cur.fetchall() if cur.description else []
    return connection.execute(statement, params).fetchall()


def _commit(connection, is_postgres: bool) -> None:
    if not (is_postgres and _pg_autocommit(connection)):
        connection.commit()


def ensure_table(connection, is_postgres: bool, table: str) -> None:
    """Erstellt die Tracking-Tabelle einer Reihe."""
    ts = "TIMESTAMPTZ NOT NULL DEFAULT NOW()" if is_postgres else "TEXT NOT NULL DEFAULT (datetime('now'))"
    _run(connection, is_postgres, f"""
        CREATE TABLE IF NOT EXISTS {_table(table)} (
            id          TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at  {ts}
        )
    """)  # nosec B608 - Tabellenname aus _TABLES
    _commit(connection, is_postgres)


def applied_ids(connection, is_postgres: bool, table: str) -> set[str]:
    """Gibt die IDs aller bereits ausgefuehrten Migrationen einer Reihe zurueck."""
    return {row[0] for row in _run(connection, is_postgres, f"SELECT id FROM {_table(table)}")}  # nosec B608


def table_exists(connection, is_postgres: bool, table: str) -> bool:
    if is_postgres:
        rows = _run(connection, True, "SELECT 1 FROM information_schema.tables "
                                      "WHERE table_schema = current_schema() AND table_name = ?", (table,))
    else:
        rows = _run(connection, False, "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,))
    return bool(rows)


def take_over_legacy_board_migrations(connection, is_postgres: bool) -> None:
    """Traegt die Board-Migrationen bis v0.7.0 aus ``_migrations`` in ``board_migrations`` nach.

    Einzeln je Migration, bei jedem Start und beliebig oft; traegt nur nach, loescht nie.
    So greift die Uebernahme auch nach dem Wiederherstellen eines Backups von vor dem Schnitt.
    """
    if not table_exists(connection, is_postgres, PERSONAL_TABLE):
        return                                    # reine Board-Datenbank
    marks = ", ".join("?" for _ in LEGACY_BOARD_IDS)
    _run(connection, is_postgres,
         f"INSERT INTO {BOARD_TABLE} (id, description) "                              # nosec B608
         f"SELECT id, description FROM {PERSONAL_TABLE} s WHERE s.id IN ({marks}) "
         f"AND NOT EXISTS (SELECT 1 FROM {BOARD_TABLE} t WHERE t.id = s.id)",
         LEGACY_BOARD_IDS)
    _commit(connection, is_postgres)


def _has_column(connection, is_postgres: bool, table: str, column: str) -> bool:
    if is_postgres:
        with connection.cursor() as cur:
            cur.execute("SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() "
                        "AND table_name = %s AND column_name = %s", (table, column))
            return cur.fetchone() is not None
    # PRAGMA nimmt keine Parameter; Tabellennamen kommen nur aus den Migrationslisten (Konstanten)
    return any(row[1] == column for row in connection.execute(f"PRAGMA table_info({table})"))  # nosec B608


def _execute(connection, is_postgres: bool, migration: Migration, statement: str) -> None:
    try:
        if is_postgres:
            with connection.cursor() as cur:
                cur.execute(statement)
        else:
            connection.execute(statement)
    except Exception as e:
        raise MigrationError(migration.id, statement, e) from e


def _apply_migration(connection, migration: Migration, is_postgres: bool) -> None:
    """Fuehrt eine einzelne Migration aus (innerhalb der Transaktion des Runners)."""
    for table, column, definition in migration.columns:
        if not _has_column(connection, is_postgres, table, column):
            _execute(connection, is_postgres, migration, f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    for statement in migration.statements:
        _execute(connection, is_postgres, migration, statement)
    if migration.fn:
        migration.fn(connection, is_postgres)


def _pg_autocommit(connection) -> bool:
    return bool(getattr(connection, "autocommit", False))


def _begin(connection, is_postgres: bool) -> None:
    if is_postgres:
        if _pg_autocommit(connection):            # ohne BEGIN liefe jede Anweisung fuer sich
            with connection.cursor() as cur:
                cur.execute("BEGIN")
        return
    if connection.in_transaction:                 # fremde halbe Arbeit nicht mit festschreiben
        raise RuntimeError("Vor der Migration ist noch eine Transaktion offen.")
    connection.execute("BEGIN IMMEDIATE")         # DDL ist in SQLite transaktional


def _finish(connection, is_postgres: bool, ok: bool) -> None:
    if is_postgres and _pg_autocommit(connection):
        with connection.cursor() as cur:
            cur.execute("COMMIT" if ok else "ROLLBACK")
    elif ok:
        connection.commit()
    else:
        connection.rollback()


def _record(connection, migration: Migration, is_postgres: bool, table: str) -> None:
    """Markiert eine Migration als ausgefuehrt."""
    _run(connection, is_postgres, f"INSERT INTO {_table(table)} (id, description) VALUES (?, ?)",  # nosec B608
         (migration.id, migration.description))


def _advisory_lock(connection, is_postgres: bool, lock: bool) -> None:
    if not is_postgres:
        return                                    # SQLite: BEGIN IMMEDIATE sperrt die Datei
    with connection.cursor() as cur:
        cur.execute("SELECT pg_advisory_lock(%s)" if lock else "SELECT pg_advisory_unlock(%s)",
                    (ADVISORY_LOCK_KEY,))
    _commit(connection, is_postgres)


@contextmanager
def advisory_lock(connection, is_postgres: bool):
    """Sperre fuer Schema und Migrationen unter PostgreSQL (wiederholt in derselben Sitzung erlaubt)."""
    _advisory_lock(connection, is_postgres, True)
    try:
        yield
    finally:
        try:
            _advisory_lock(connection, is_postgres, False)
        except Exception as unlock_error:  # noqa: BLE001 - Sperre faellt spaetestens mit der Verbindung
            logger.warning("Advisory-Sperre der Migrationen nicht freigegeben: %s", unlock_error)


def run_series(connection, is_postgres: bool, migrations: list[Migration], table: str) -> list[str]:
    """Fuehrt alle ausstehenden Migrationen einer Reihe aus, jede in einer eigenen Transaktion.

    Returns: Liste der ausgefuehrten Migrations-IDs.
    Raises: MigrationError, wenn eine Migration fehlschlaegt; dann ist sie
        zurueckgerollt, nicht eingetragen, und spaetere laufen nicht.
    """
    if not is_postgres and connection.in_transaction:   # fremde halbe Arbeit nicht mit festschreiben
        connection.rollback()
        raise MigrationError("(vor den Migrationen)", None,
                             RuntimeError("Vor den Migrationen war noch eine Transaktion offen."))
    _advisory_lock(connection, is_postgres, True)
    try:
        ensure_table(connection, is_postgres, table)
        if table == BOARD_TABLE:
            take_over_legacy_board_migrations(connection, is_postgres)
        applied = applied_ids(connection, is_postgres, table)
        executed = []
        for migration in migrations:
            if migration.id in applied:
                continue
            try:
                _begin(connection, is_postgres)
                _apply_migration(connection, migration, is_postgres)
                _record(connection, migration, is_postgres, table)
                _finish(connection, is_postgres, ok=True)
            except Exception as e:
                try:
                    _finish(connection, is_postgres, ok=False)
                except Exception as rollback_error:  # noqa: BLE001 - die eigentliche Ursache bleibt die Meldung
                    logger.error("Rollback der Migration %s fehlgeschlagen: %s", migration.id, rollback_error)
                logger.error("Migration %s fehlgeschlagen, zurueckgerollt: %s", migration.id, e)
                if isinstance(e, MigrationError):
                    raise
                raise MigrationError(migration.id, None, e) from e
            executed.append(migration.id)
            logger.info("Migration %s ausgefuehrt: %s", migration.id, migration.description)
        return executed
    finally:
        try:
            _advisory_lock(connection, is_postgres, False)
        except Exception as unlock_error:  # noqa: BLE001 - Sperre faellt spaetestens mit der Verbindung
            logger.warning("Advisory-Sperre der Migrationen nicht freigegeben: %s", unlock_error)


def run_extension_migrations(connection, is_postgres: bool, migrations: list[Migration], table: str) -> list[str]:
    """Migrationsreihe einer Erweiterung mit eigener Tracking-Tabelle (``<name>_migrations``, T4).

    Gleiches Verhalten wie die Board-Reihe (eine Transaktion je Migration, fail-closed,
    Advisory-Sperre); keine Uebernahme alter IDs. Erst nach der Board-Reihe aufrufen, wenn
    die Erweiterung Board-Tabellen referenziert."""
    if table in _TABLES:
        raise ValueError(f"{table} gehoert nicht zu einer Erweiterung.")
    return run_series(connection, is_postgres, migrations, _table(table))


def run_board_migrations(connection, is_postgres: bool = False,
                         migrations: list[Migration] | None = None) -> list[str]:
    """Migrationsreihe des Boards (``board_migrations``); legt auf leerer Datenbank das Board an."""
    return run_series(connection, is_postgres, BOARD_MIGRATIONS if migrations is None else migrations, BOARD_TABLE)
