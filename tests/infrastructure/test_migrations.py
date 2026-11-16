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
    # 011 ergaenzt messages; der alte Runner hatte das Fehlen der Tabelle still uebergangen (R1)
    conn.execute("CREATE TABLE messages (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, content TEXT NOT NULL)")
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
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "tool_events" in tables


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
    conn.execute("CREATE TABLE messages (id TEXT PRIMARY KEY, content TEXT NOT NULL, origin TEXT)")
    conn.commit()

    # Vorhandene Spalten werden erkannt; die Migrationen gelten als erledigt (R1)
    run_migrations(conn, is_postgres=False)
    applied = _get_applied(conn, is_postgres=False)
    assert {"001_audit_token_columns", "002_conversation_rules", "003_agent_universal_fields",
            "004_agent_api_key_enc", "011_message_origin"} <= applied


def test_all_migrations_have_unique_ids():
    ids = [m.id for m in MIGRATIONS]
    assert len(ids) == len(set(ids)), "Doppelte Migrations-IDs gefunden"


def test_all_migrations_have_description():
    for m in MIGRATIONS:
        assert m.description, f"Migration {m.id} hat keine Beschreibung"


# ── R1 (conclave#31): Migrationen fail-closed ─────────────────────────────

def _broken(created_table="r1_a"):
    return [
        Migration(id="900_broken", description="zweite Anweisung scheitert",
                  statements=(f"CREATE TABLE {created_table} (x INTEGER)",
                              "INSERT INTO conversations (id, status) VALUES ('r1', 'open')",
                              "INSERT INTO gibt_es_nicht VALUES (1)")),
        Migration(id="901_after", description="darf nicht laufen", statements=("CREATE TABLE r1_b (x INTEGER)",)),
    ]


def _tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_failing_migration_aborts_and_leaves_nothing_behind(db):
    from conclave.infrastructure.migrations import MigrationError
    run_migrations(db, is_postgres=False)
    with pytest.raises(MigrationError) as err:
        run_migrations(db, is_postgres=False, migrations=_broken())
    assert "900_broken" in str(err.value) and "gibt_es_nicht" in str(err.value)
    assert not db.in_transaction                                       # keine offene Transaktion
    assert not {"r1_a", "r1_b"} & _tables(db)                          # DDL zurueckgerollt, 901 nicht gelaufen
    assert db.execute("SELECT count(*) FROM conversations WHERE id = 'r1'").fetchone() == (0,)
    assert not {"900_broken", "901_after"} & _get_applied(db, is_postgres=False)


def test_repaired_migration_runs_cleanly_afterwards(db):
    from conclave.infrastructure.migrations import MigrationError
    run_migrations(db, is_postgres=False)
    with pytest.raises(MigrationError):
        run_migrations(db, is_postgres=False, migrations=_broken())
    fixed = [Migration(id="900_broken", description="repariert", statements=("CREATE TABLE r1_a (x INTEGER)",)),
             _broken()[1]]
    assert run_migrations(db, is_postgres=False, migrations=fixed) == ["900_broken", "901_after"]
    assert {"r1_a", "r1_b"} <= _tables(db)


def test_fresh_database_has_no_migration_warnings_and_records_all(tmp_path, caplog):
    from conclave.infrastructure.sqlite.connection import ThreadLocalConnection
    from conclave.infrastructure.sqlite.schema import initialize_schema
    conn = ThreadLocalConnection(tmp_path / "frisch.db")
    with caplog.at_level("INFO", logger="conclave.migrations"):
        initialize_schema(conn)
        initialize_schema(conn)                                        # zweiter Start
    assert [r for r in caplog.records if r.levelno >= 30] == []
    assert _get_applied(conn, is_postgres=False) == {m.id for m in MIGRATIONS}


def test_column_migration_adds_only_missing_columns(db):
    db.execute("ALTER TABLE agents ADD COLUMN preset TEXT NOT NULL DEFAULT ''")   # teilweise vorhanden
    db.commit()
    run_migrations(db, is_postgres=False)
    cols = {row[1] for row in db.execute("PRAGMA table_info(agents)")}
    assert {"preset", "api_url", "response_path", "message_format"} <= cols
    assert "003_agent_universal_fields" in _get_applied(db, is_postgres=False)



def test_open_transaction_of_the_caller_is_not_committed(db):
    """Review R1: halbe Arbeit des Aufrufers wird nicht still mit festgeschrieben."""
    from conclave.infrastructure.migrations import MigrationError
    run_migrations(db, is_postgres=False)
    db.execute("INSERT INTO conversations (id, status) VALUES ('halb', 'open')")      # offene Transaktion
    assert db.in_transaction
    with pytest.raises(MigrationError, match="Transaktion offen"):
        run_migrations(db, is_postgres=False, migrations=_broken())
    assert not db.in_transaction
    assert db.execute("SELECT count(*) FROM conversations WHERE id = 'halb'").fetchone() == (0,)
    assert "r1_a" not in _tables(db)                                   # keine Migration gelaufen


def test_commit_failure_is_reported_with_the_migration(db, monkeypatch):
    import conclave.infrastructure.migrations as m
    run_migrations(db, is_postgres=False)
    real = m._finish

    def failing_commit(connection, is_postgres, ok):
        if ok:
            raise RuntimeError("commit gescheitert")
        real(connection, is_postgres, ok)

    monkeypatch.setattr(m, "_finish", failing_commit)
    ok = [Migration(id="902_ok", description="laeuft, Commit scheitert", statements=("CREATE TABLE r1_c (x INTEGER)",))]
    with pytest.raises(m.MigrationError, match="902_ok.*commit gescheitert"):
        run_migrations(db, is_postgres=False, migrations=ok)
    assert "r1_c" not in _tables(db) and not db.in_transaction
