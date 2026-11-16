"""T1: eigene Migrationsreihe des Boards (``board_migrations``) und Uebernahme aus ``_migrations``.

Faelle aus der Abnahme von conclave#69:
- leere Datenbank nur mit dem Board-Paket
- Datenbank aus 0.6.x (nur ``012_board``)
- Datenbank aus 0.7.0 (alle sechs Board-Migrationen in ``_migrations``)
- Backup von vor dem Schnitt wiederhergestellt
- Rueckschritt auf 0.7.0 nach dem Schnitt
- beliebige Reihenfolge der beiden Reihen
"""

import shutil
import sqlite3

import pytest

from conclave.infrastructure.migrations import MIGRATIONS, run_migrations
from conclave.infrastructure.sqlite.schema import initialize_schema
from conclave_board.infrastructure.migrations import (
    BOARD_MIGRATIONS, LEGACY_BOARD_IDS, MigrationError, Migration, applied_ids, run_board_migrations,
)

# Alle IDs in _migrations, die v0.7.0 kennt (eine 0.7.0 nach dem Schnitt darf nichts nachholen)
V070_IDS = {
    "001_audit_token_columns", "002_conversation_rules", "003_agent_universal_fields", "004_agent_api_key_enc",
    "005_personal_runs", "006_tool_events", "007_context_reports", "008_agent_max_messages",
    "009_consultations", "010_consultation_channels", "011_message_origin", "012_board",
    "013_conversation_model_read", "014_board_rank", "015_board_history", "016_board_review",
    "017_board_control", "018_consultation_lease", "019_run_origin", "020_board_initiatives",
}


def _connect(path):
    conn = sqlite3.connect(str(path), isolation_level="IMMEDIATE")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _tables(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _rows(conn, table):
    return sorted(conn.execute(f"SELECT id, description FROM {table}").fetchall())  # nosec B608 - Testkonstante


def _schema(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL "
                                       "AND name NOT IN ('_migrations', 'board_migrations')")}


def _old_personal_db(path, upto: str | None = None):
    """Datenbank wie vor dem Schnitt: nur Personal-Schema und eine Liste in _migrations.

    ``upto`` begrenzt die Liste (z. B. "012_board" fuer einen Stand aus 0.6.x)."""
    conn = _connect(path)
    # Grundschema von Personal ohne die Board-Reihe: wie initialize_schema vor T1
    import conclave.infrastructure.sqlite.schema as schema
    original = schema.run_board_migrations
    schema.run_board_migrations = lambda *a, **k: []
    try:
        migrations = MIGRATIONS
        if upto is not None:
            ids = [m.id for m in MIGRATIONS]
            migrations = MIGRATIONS[: ids.index(upto) + 1]
        schema.run_migrations = lambda connection, is_postgres=False: run_migrations(connection, is_postgres,
                                                                                      migrations=migrations)
        initialize_schema(conn)
    finally:
        schema.run_board_migrations = original
        schema.run_migrations = run_migrations
    assert "board_migrations" not in _tables(conn)
    return conn


# ── Leere Datenbank, nur Board ─────────────────────────────────────────────

def test_empty_database_gets_only_the_board_series(tmp_path):
    conn = _connect(tmp_path / "board.db")
    assert run_board_migrations(conn) == [m.id for m in BOARD_MIGRATIONS]
    tables = _tables(conn)
    assert {"board_projects", "board_tasks", "board_comments", "board_initiatives", "board_migrations"} <= tables
    assert "_migrations" not in tables and "conversations" not in tables
    assert run_board_migrations(conn) == []                                # zweiter Start: nichts mehr


# ── Datenbank aus 0.7.0 ───────────────────────────────────────────────────

def test_database_from_0_7_0_takes_over_all_six_without_running_them(tmp_path):
    conn = _old_personal_db(tmp_path / "c.db")
    before = _rows(conn, "_migrations")
    assert {r[0] for r in before} == V070_IDS
    assert run_board_migrations(conn) == []                                # nichts neu ausgefuehrt
    assert applied_ids(conn, False, "board_migrations") == set(LEGACY_BOARD_IDS)
    assert _rows(conn, "_migrations") == before                            # _migrations unveraendert


def test_takeover_happens_on_every_start(tmp_path):
    """Auch spaeter Eingetragenes wird uebernommen; wiederholbar ohne Wirkung."""
    conn = _old_personal_db(tmp_path / "c.db")
    run_board_migrations(conn)
    conn.execute("DELETE FROM board_migrations WHERE id = '016_board_review'")
    conn.commit()
    assert run_board_migrations(conn) == []
    assert "016_board_review" in applied_ids(conn, False, "board_migrations")
    assert run_board_migrations(conn) == []


# ── Datenbank aus 0.6.x ───────────────────────────────────────────────────

def test_database_from_0_6_takes_over_012_and_runs_the_rest(tmp_path):
    conn = _old_personal_db(tmp_path / "c.db", upto="012_board")
    assert {r[0] for r in _rows(conn, "_migrations")} & set(LEGACY_BOARD_IDS) == {"012_board"}
    conn.execute("INSERT INTO board_projects (id, slug, name, created_at) VALUES ('p1', 'alt', 'Alt', '2026-10-01')")
    conn.execute("INSERT INTO board_counters (project_id, next_number) VALUES ('p1', 2)")
    conn.execute("INSERT INTO board_tasks (id, project_id, number, title, status, position, created_at, updated_at) "
                 "VALUES ('t1', 'p1', 1, 'aus 0.6', 'todo', 3.0, '2026-10-01', '2026-10-01')")
    conn.commit()

    executed = run_board_migrations(conn)
    assert executed == ["014_board_rank", "015_board_history", "016_board_review", "017_board_control",
                        "020_board_initiatives"]
    assert applied_ids(conn, False, "board_migrations") == set(LEGACY_BOARD_IDS)
    # Das heutige 012 legt rank schon mit an; "rank aus position" (014 auf echtem 0.6-Schema) pruefen
    # test_board_repository und der Upgrade-Test mit dem Paket 0.6.0
    assert conn.execute("SELECT title FROM board_tasks WHERE id = 't1'").fetchone() == ("aus 0.6",)

    # Danach Personal: holt seine eigenen nach, die Board-Migrationen laufen wirkungslos noch einmal
    run_migrations(conn)
    assert {r[0] for r in _rows(conn, "_migrations")} == V070_IDS
    assert conn.execute("SELECT title FROM board_tasks WHERE id = 't1'").fetchone() == ("aus 0.6",)


# ── Backup von vor dem Schnitt ────────────────────────────────────────────

def test_restored_backup_from_before_the_cut_is_taken_over_on_start(tmp_path):
    backup = tmp_path / "vorher.db"
    _old_personal_db(backup).close()
    current = tmp_path / "conclave.db"
    conn = _connect(current)
    initialize_schema(conn)                                                # Stand nach dem Schnitt
    conn.close()

    shutil.copyfile(backup, current)                                       # Wiederherstellen
    conn = _connect(current)
    assert "board_migrations" not in _tables(conn)
    initialize_schema(conn)                                                # naechster Start
    assert applied_ids(conn, False, "board_migrations") == set(LEGACY_BOARD_IDS)
    assert {r[0] for r in _rows(conn, "_migrations")} == V070_IDS


# ── Rueckschritt auf 0.7.0 ────────────────────────────────────────────────

def test_database_after_the_cut_still_satisfies_0_7_0(tmp_path):
    """0.7.0 liest nur _migrations: Dort steht alles, was 0.7.0 kennt, also holt es nichts nach."""
    conn = _connect(tmp_path / "neu.db")
    initialize_schema(conn)
    assert {r[0] for r in _rows(conn, "_migrations")} >= V070_IDS
    assert applied_ids(conn, False, "board_migrations") == set(LEGACY_BOARD_IDS)


def test_personal_on_a_board_only_database_reruns_the_old_board_migrations_harmlessly(tmp_path):
    conn = _connect(tmp_path / "board.db")
    run_board_migrations(conn)
    initialize_schema(conn)                                                # Personal oeffnet sie danach
    assert {r[0] for r in _rows(conn, "_migrations")} == V070_IDS
    assert applied_ids(conn, False, "board_migrations") == set(LEGACY_BOARD_IDS)


# ── Reihenfolge ───────────────────────────────────────────────────────────

def test_order_of_the_two_series_does_not_matter(tmp_path):
    personal_first = _connect(tmp_path / "a.db")
    initialize_schema(personal_first)

    board_first = _connect(tmp_path / "b.db")
    run_board_migrations(board_first)
    initialize_schema(board_first)

    assert _schema(board_first) == _schema(personal_first)


def test_no_migration_of_one_series_touches_tables_of_the_other():
    import inspect
    board_ids = {m.id for m in BOARD_MIGRATIONS}
    for migration in MIGRATIONS:
        source = inspect.getsource(migration.fn) if migration.fn else ""
        text = " ".join([source, *migration.statements, *(t for t, _, _ in migration.columns)])
        if migration.id in board_ids:
            continue
        assert "board_" not in text, migration.id


# ── Fehler bleiben fail-closed (R1) ────────────────────────────────────────

def test_failing_board_migration_stops_and_records_nothing(tmp_path):
    conn = _connect(tmp_path / "board.db")
    broken = BOARD_MIGRATIONS + [Migration(id="999_kaputt", description="Test",
                                           statements=("CREATE TABLE board_x (a INTEGER)", "KEIN SQL"))]
    with pytest.raises(MigrationError, match="999_kaputt"):
        run_board_migrations(conn, migrations=broken)
    assert "999_kaputt" not in applied_ids(conn, False, "board_migrations")
    assert "board_x" not in _tables(conn)
