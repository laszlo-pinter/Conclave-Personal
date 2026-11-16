"""T1: Migrationsreihe des Boards gegen ein echtes PostgreSQL.

Laeuft nur mit CONCLAVE_TEST_POSTGRES_DSN (CI-Job "postgres"); lokal sonst uebersprungen.
- reine Board-Datenbank: nur die Board-Reihe, keine Tabellen von Personal
- Personal-Datenbank aus 0.7.0: Uebernahme ohne erneute Ausfuehrung
- Advisory-Sperre: Ein zweiter Start wartet, bis der erste fertig ist
"""

import os
import threading
import time

import pytest

DSN = os.environ.get("CONCLAVE_TEST_POSTGRES_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="CONCLAVE_TEST_POSTGRES_DSN nicht gesetzt")

psycopg2 = pytest.importorskip("psycopg2")

from conclave_board.infrastructure.migrations import (  # noqa: E402
    ADVISORY_LOCK_KEY, BOARD_MIGRATIONS, LEGACY_BOARD_IDS, applied_ids, run_board_migrations,
)


def _connect():
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    return conn


@pytest.fixture
def pg():
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE")
        cur.execute("CREATE SCHEMA public")
    yield conn
    conn.close()


def _tables(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()")
        return {r[0] for r in cur.fetchall()}


def test_board_only_database(pg):
    assert run_board_migrations(pg, is_postgres=True) == [m.id for m in BOARD_MIGRATIONS]
    tables = _tables(pg)
    assert {"board_tasks", "board_initiatives", "board_migrations"} <= tables
    assert "_migrations" not in tables and "conversations" not in tables
    assert run_board_migrations(pg, is_postgres=True) == []


def test_personal_database_takes_over_the_old_board_migrations(pg):
    from conclave.infrastructure.migrations import run_migrations
    from conclave.infrastructure.postgres import schema
    original = schema.run_board_migrations
    schema.run_board_migrations = lambda *a, **k: []          # Stand vor dem Schnitt: nur _migrations
    try:
        schema.initialize_schema(pg)
    finally:
        schema.run_board_migrations = original
    assert "board_migrations" not in _tables(pg)
    assert run_board_migrations(pg, is_postgres=True) == []
    assert applied_ids(pg, True, "board_migrations") == set(LEGACY_BOARD_IDS)
    assert run_migrations(pg, is_postgres=True) == []


def test_second_start_waits_for_the_advisory_lock(pg):
    holder = _connect()
    with holder.cursor() as cur:
        cur.execute("SELECT pg_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
    done = threading.Event()
    errors = []

    def start():
        conn = _connect()
        try:
            run_board_migrations(conn, is_postgres=True)
        except Exception as e:  # noqa: BLE001 - im Test sichtbar machen
            errors.append(e)
        finally:
            conn.close()
            done.set()

    worker = threading.Thread(target=start)
    worker.start()
    time.sleep(1.0)
    assert not done.is_set()                                   # wartet auf die Sperre
    with holder.cursor() as cur:
        cur.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))
    holder.close()
    assert done.wait(30) and errors == []
    worker.join()
    assert "board_tasks" in _tables(pg)
