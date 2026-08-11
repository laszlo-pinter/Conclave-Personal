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
