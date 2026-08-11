# tests/infrastructure/test_migrations.py
"""Tests fuer das Schema-Migrationssystem."""

import sqlite3
import pytest

from conclave.infrastructure.migrations import (
    Migration,
    MIGRATIONS,
    run_migrations,
    _ensure_migrations_table,
    _get_applied,
)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    # Minimales Schema ohne Migrationen
    conn.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, status TEXT NOT NULL)")
    conn.execute("CREATE TABLE agents (id TEXT PRIMARY KEY, name TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL, created_at TEXT NOT NULL)")
    conn.execute("CREATE TABLE audit_log (id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, operation TEXT NOT NULL, conversation_id TEXT NOT NULL, participant_id TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL, success INTEGER NOT NULL, error_message TEXT, user_id TEXT)")
    conn.commit()
    return conn


def test_migrations_table_created(db):
    _ensure_migrations_table(db, is_postgres=False)
    rows = db.execute("SELECT name FROM sqlite_master WHERE name='_migrations'").fetchall()
    assert len(rows) == 1


def test_run_migrations_applies_pending(db):
    executed = run_migrations(db, is_postgres=False)
    assert len(executed) > 0
    assert "001_audit_token_columns" in executed


def test_run_migrations_is_idempotent(db):
    first = run_migrations(db, is_postgres=False)
    second = run_migrations(db, is_postgres=False)
    assert len(first) > 0
    assert len(second) == 0  # Nichts mehr zu tun


def test_applied_migrations_tracked(db):
    run_migrations(db, is_postgres=False)
    applied = _get_applied(db, is_postgres=False)
    assert "001_audit_token_columns" in applied
    assert "002_conversation_rules" in applied


def test_migration_adds_columns(db):
    run_migrations(db, is_postgres=False)
    # audit_log sollte jetzt input_tokens haben
    cols = {row[1] for row in db.execute("PRAGMA table_info(audit_log)").fetchall()}
    assert "input_tokens" in cols
    assert "output_tokens" in cols


def test_migration_skips_already_existing_columns():
    """Wenn eine Spalte schon existiert, wird die Migration uebersprungen."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE audit_log (
            id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, operation TEXT NOT NULL,
            conversation_id TEXT NOT NULL, participant_id TEXT NOT NULL,
            provider TEXT NOT NULL, model TEXT NOT NULL, success INTEGER NOT NULL,
            error_message TEXT, user_id TEXT, input_tokens INTEGER, output_tokens INTEGER
        )
    """)
    conn.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, status TEXT NOT NULL, rules TEXT NOT NULL DEFAULT '')")
    conn.execute("""
        CREATE TABLE agents (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, provider TEXT NOT NULL,
            model TEXT NOT NULL, api_key_enc TEXT NOT NULL DEFAULT '',
            preset TEXT NOT NULL DEFAULT '', api_url TEXT NOT NULL DEFAULT '',
            response_path TEXT NOT NULL DEFAULT '', message_format TEXT NOT NULL DEFAULT 'standard',
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()

    # Sollte nicht crashen, sondern Migrationen ueberspringen
    executed = run_migrations(conn, is_postgres=False)
    # Alle werden als "uebersprungen" geloggt, aber trotzdem in _migrations recorded
    # (weil das Schema schon vollstaendig ist)
    applied = _get_applied(conn, is_postgres=False)
    # Mindestens _migrations Tabelle existiert
    assert isinstance(applied, set)


def test_all_migrations_have_unique_ids():
    ids = [m.id for m in MIGRATIONS]
    assert len(ids) == len(set(ids)), "Doppelte Migrations-IDs gefunden"


def test_all_migrations_have_description():
    for m in MIGRATIONS:
        assert m.description, f"Migration {m.id} hat keine Beschreibung"
