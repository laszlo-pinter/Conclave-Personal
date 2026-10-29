# src/conclave/infrastructure/migrations.py
"""Einfaches Schema-Migrationssystem.

Jede Migration hat eine ID und ein SQL-Statement (oder eine Funktion).
Die Tabelle _migrations trackt welche Migrationen bereits gelaufen sind.
Neue Migrationen werden beim Start automatisch ausgefuehrt.

Migrationen sind idempotent und werden nur einmal ausgefuehrt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger("conclave.migrations")


@dataclass
class Migration:
    id: str
    description: str
    sql: str | None = None
    fn: Callable | None = None


# ── Alle Migrationen in chronologischer Reihenfolge ─────────────────────

MIGRATIONS: list[Migration] = [
    Migration(
        id="001_audit_token_columns",
        description="Token-Spalten fuer audit_log",
        sql="ALTER TABLE audit_log ADD COLUMN input_tokens INTEGER; "
            "ALTER TABLE audit_log ADD COLUMN output_tokens INTEGER",
    ),
    Migration(
        id="002_conversation_rules",
        description="Rules-Spalte fuer Conversations",
        sql="ALTER TABLE conversations ADD COLUMN rules TEXT NOT NULL DEFAULT ''",
    ),
    Migration(
        id="003_agent_universal_fields",
        description="UniversalAdapter-Felder fuer Agents",
        sql="ALTER TABLE agents ADD COLUMN preset TEXT NOT NULL DEFAULT ''; "
            "ALTER TABLE agents ADD COLUMN api_url TEXT NOT NULL DEFAULT ''; "
            "ALTER TABLE agents ADD COLUMN response_path TEXT NOT NULL DEFAULT ''; "
            "ALTER TABLE agents ADD COLUMN message_format TEXT NOT NULL DEFAULT 'standard'",
    ),
    Migration(
        id="004_agent_api_key_enc",
        description="Verschluesselte API-Key-Spalte fuer Agents",
        sql="ALTER TABLE agents ADD COLUMN api_key_enc TEXT NOT NULL DEFAULT ''",
    ),
    Migration(
        id="005_personal_runs",
        description="Personal-Runs und UsageRecords",
        fn=lambda connection, is_postgres: _create_runs_tables(connection, is_postgres),
    ),
    Migration(
        id="006_tool_events",
        description="Tool-Events fuer deterministische Backend-Aktionen",
        fn=lambda connection, is_postgres: _create_tool_events_table(connection, is_postgres),
    ),
    Migration(
        id="007_context_reports",
        description="Kontext-Reports je Modellaufruf (welcher Kontext an den Provider ging)",
        fn=lambda connection, is_postgres: _create_context_reports_table(connection, is_postgres),
    ),
    Migration(
        id="008_agent_max_messages",
        description="Kuerzungslimit pro Agent (NULL = globaler Default, 0 = keine Kuerzung)",
        sql="ALTER TABLE agents ADD COLUMN max_messages INTEGER",
    ),
    Migration(
        id="009_consultations",
        description="Consultations (Zweitmeinung zu Kanzo-Tickets) und ihre Zustellungen",
        fn=lambda connection, is_postgres: _create_consultations_tables(connection, is_postgres),
    ),
    Migration(
        id="010_consultation_channels",
        description="Consultation-Kanal beschreibt den Zugang: rest -> human, mcp -> agent (E3)",
        sql="UPDATE consultations SET channel = 'human' WHERE channel = 'rest'; "
            "UPDATE consultations SET channel = 'agent' WHERE channel = 'mcp'",
    ),
    Migration(
        id="011_message_origin",
        description="Herkunft von User-Nachrichten (human/agent, NULL = unbekannt)",
        sql="ALTER TABLE messages ADD COLUMN origin TEXT",
    ),
    Migration(
        id="012_board",
        description="Board: Projekte, Tickets, Kommentare, Verlauf, Zaehler (Plan board.md, B1)",
        fn=lambda connection, is_postgres: _create_board_tables(connection, is_postgres),
    ),
]


def _create_runs_tables(connection, is_postgres: bool) -> None:
    if is_postgres:
        with connection.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    id              TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    kind            TEXT NOT NULL,
                    participants    TEXT NOT NULL,
                    started_at      TIMESTAMPTZ NOT NULL,
                    finished_at     TIMESTAMPTZ,
                    status          TEXT NOT NULL,
                    error           TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS usage_records (
                    id              TEXT PRIMARY KEY,
                    run_id          TEXT NOT NULL REFERENCES runs(id),
                    conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    participant_id  TEXT NOT NULL,
                    provider        TEXT NOT NULL,
                    model           TEXT NOT NULL,
                    input_tokens    INTEGER,
                    output_tokens   INTEGER,
                    created_at      TIMESTAMPTZ NOT NULL
                )
            """)
    else:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id              TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                kind            TEXT NOT NULL,
                participants    TEXT NOT NULL,
                started_at      TEXT NOT NULL,
                finished_at     TEXT,
                status          TEXT NOT NULL,
                error           TEXT,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id)
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS usage_records (
                id              TEXT PRIMARY KEY,
                run_id          TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                participant_id  TEXT NOT NULL,
                provider        TEXT NOT NULL,
                model           TEXT NOT NULL,
                input_tokens    INTEGER,
                output_tokens   INTEGER,
                created_at      TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES runs(id),
                FOREIGN KEY(conversation_id) REFERENCES conversations(id)
            )
        """)


def _create_tool_events_table(connection, is_postgres: bool) -> None:
    if is_postgres:
        with connection.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tool_events (
                    id              TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    message_id      TEXT REFERENCES messages(id),
                    run_id          TEXT REFERENCES runs(id),
                    participant_id  TEXT NOT NULL,
                    tool            TEXT NOT NULL,
                    status          TEXT NOT NULL,
                    input_json      TEXT NOT NULL,
                    output_json     TEXT NOT NULL,
                    error           TEXT,
                    created_at      TIMESTAMPTZ NOT NULL
                )
            """)
    else:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS tool_events (
                id              TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                message_id      TEXT,
                run_id          TEXT,
                participant_id  TEXT NOT NULL,
                tool            TEXT NOT NULL,
                status          TEXT NOT NULL,
                input_json      TEXT NOT NULL,
                output_json     TEXT NOT NULL,
                error           TEXT,
                created_at      TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id),
                FOREIGN KEY(message_id) REFERENCES messages(id),
                FOREIGN KEY(run_id) REFERENCES runs(id)
            )
        """)


def _create_context_reports_table(connection, is_postgres: bool) -> None:
    index = "CREATE INDEX IF NOT EXISTS idx_context_reports_message ON context_reports(message_id)"
    if is_postgres:
        with connection.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS context_reports (
                    id              TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    participant_id  TEXT NOT NULL,
                    message_id      TEXT REFERENCES messages(id),
                    run_id          TEXT REFERENCES runs(id),
                    created_at      TIMESTAMPTZ NOT NULL,
                    report_json     TEXT NOT NULL
                )
            """)
            cur.execute(index)
    else:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS context_reports (
                id              TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                participant_id  TEXT NOT NULL,
                message_id      TEXT,
                run_id          TEXT,
                created_at      TEXT NOT NULL,
                report_json     TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id),
                FOREIGN KEY(message_id) REFERENCES messages(id),
                FOREIGN KEY(run_id) REFERENCES runs(id)
            )
        """)
        connection.execute(index)


def _create_consultations_tables(connection, is_postgres: bool) -> None:
    indexes = (
        "CREATE INDEX IF NOT EXISTS idx_consultations_ref ON consultations(source, source_ref, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_consultations_status ON consultations(status)",
        "CREATE INDEX IF NOT EXISTS idx_deliveries_consultation ON consultation_deliveries(consultation_id)",
    )
    if is_postgres:
        with connection.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS consultations (
                    id               TEXT PRIMARY KEY,
                    source           TEXT NOT NULL,
                    source_ref       TEXT NOT NULL,
                    question         TEXT NOT NULL,
                    reviewers_json   TEXT NOT NULL,
                    channel          TEXT NOT NULL,
                    mode             TEXT NOT NULL,
                    context          TEXT NOT NULL DEFAULT '',
                    requested_by     TEXT NOT NULL DEFAULT '',
                    include_previous BOOLEAN NOT NULL DEFAULT FALSE,
                    status           TEXT NOT NULL,
                    error            TEXT,
                    conversation_id  TEXT,
                    created_at       TIMESTAMPTZ NOT NULL,
                    finished_at      TIMESTAMPTZ
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS consultation_deliveries (
                    id              TEXT PRIMARY KEY,
                    consultation_id TEXT NOT NULL REFERENCES consultations(id),
                    participant_id  TEXT NOT NULL,
                    message_id      TEXT,
                    marker          TEXT NOT NULL,
                    status          TEXT NOT NULL,
                    attempts        INTEGER NOT NULL DEFAULT 0,
                    error           TEXT,
                    delivered_at    TIMESTAMPTZ
                )
            """)
            for index in indexes:
                cur.execute(index)
    else:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS consultations (
                id               TEXT PRIMARY KEY,
                source           TEXT NOT NULL,
                source_ref       TEXT NOT NULL,
                question         TEXT NOT NULL,
                reviewers_json   TEXT NOT NULL,
                channel          TEXT NOT NULL,
                mode             TEXT NOT NULL,
                context          TEXT NOT NULL DEFAULT '',
                requested_by     TEXT NOT NULL DEFAULT '',
                include_previous INTEGER NOT NULL DEFAULT 0,
                status           TEXT NOT NULL,
                error            TEXT,
                conversation_id  TEXT,
                created_at       TEXT NOT NULL,
                finished_at      TEXT
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS consultation_deliveries (
                id              TEXT PRIMARY KEY,
                consultation_id TEXT NOT NULL,
                participant_id  TEXT NOT NULL,
                message_id      TEXT,
                marker          TEXT NOT NULL,
                status          TEXT NOT NULL,
                attempts        INTEGER NOT NULL DEFAULT 0,
                error           TEXT,
                delivered_at    TEXT,
                FOREIGN KEY(consultation_id) REFERENCES consultations(id)
            )
        """)
        for index in indexes:
            connection.execute(index)


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
            human       {boolean},
            assignee    TEXT,
            created_at  {ts} NOT NULL,
            updated_at  {ts} NOT NULL,
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
            updated_at  {ts}
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


# ── Runner ────────────────────────────────────────────────────────────────

def _ensure_migrations_table(connection, is_postgres: bool) -> None:
    """Erstellt die _migrations Tracking-Tabelle."""
    if is_postgres:
        with connection.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS _migrations (
                    id          TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
        connection.commit()
    else:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS _migrations (
                id          TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        connection.commit()


def _get_applied(connection, is_postgres: bool) -> set[str]:
    """Gibt die IDs aller bereits ausgefuehrten Migrationen zurueck."""
    if is_postgres:
        with connection.cursor() as cur:
            cur.execute("SELECT id FROM _migrations")
            return {row[0] for row in cur.fetchall()}
    else:
        return {row[0] for row in connection.execute("SELECT id FROM _migrations").fetchall()}


def _apply_migration(connection, migration: Migration, is_postgres: bool) -> None:
    """Fuehrt eine einzelne Migration aus."""
    if migration.fn:
        migration.fn(connection, is_postgres)
    elif migration.sql:
        statements = [s.strip() for s in migration.sql.split(";") if s.strip()]
        if is_postgres:
            with connection.cursor() as cur:
                for stmt in statements:
                    cur.execute(stmt)
        else:
            for stmt in statements:
                connection.execute(stmt)


def _record_migration(connection, migration: Migration, is_postgres: bool) -> None:
    """Markiert eine Migration als ausgefuehrt."""
    if is_postgres:
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO _migrations (id, description) VALUES (%s, %s)",
                (migration.id, migration.description),
            )
    else:
        connection.execute(
            "INSERT INTO _migrations (id, description) VALUES (?, ?)",
            (migration.id, migration.description),
        )


def run_migrations(connection, is_postgres: bool = False) -> list[str]:
    """Fuehrt alle ausstehenden Migrationen aus.

    Returns: Liste der ausgefuehrten Migrations-IDs.
    """
    _ensure_migrations_table(connection, is_postgres)
    applied = _get_applied(connection, is_postgres)
    executed = []

    for migration in MIGRATIONS:
        if migration.id in applied:
            continue
        try:
            _apply_migration(connection, migration, is_postgres)
            _record_migration(connection, migration, is_postgres)
            if is_postgres:
                connection.commit()
            else:
                connection.commit()
            executed.append(migration.id)
            logger.info("Migration %s ausgefuehrt: %s", migration.id, migration.description)
        except Exception as e:
            logger.warning("Migration %s uebersprungen (vermutlich bereits vorhanden): %s",
                           migration.id, e)
            if is_postgres:
                connection.rollback()
            # Bei SQLite kein explizites Rollback noetig

    return executed
