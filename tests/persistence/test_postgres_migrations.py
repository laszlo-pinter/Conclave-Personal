"""R1 (conclave#31): Migrationen fail-closed gegen ein echtes PostgreSQL.

Laeuft nur mit CONCLAVE_TEST_POSTGRES_DSN (CI-Job "postgres"). Die Verbindung
steht wie im Server auf Autocommit; ohne eigene Transaktion bliebe eine
halbe Migration stehen.
"""

import logging
import os

import pytest

DSN = os.environ.get("CONCLAVE_TEST_POSTGRES_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="CONCLAVE_TEST_POSTGRES_DSN nicht gesetzt")

psycopg2 = pytest.importorskip("psycopg2")

from conclave.infrastructure.migrations import MIGRATIONS, Migration, MigrationError, run_migrations  # noqa: E402


@pytest.fixture
def pg():
    conn = psycopg2.connect(DSN)
    conn.autocommit = True                       # wie im Server (api/server.py)
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE")
        cur.execute("CREATE SCHEMA public")
    yield conn
    conn.close()


def _applied(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM _migrations")
        return {r[0] for r in cur.fetchall()}


def _table_exists(conn, name):
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (name,))
        return cur.fetchone()[0] is not None


def test_fresh_database_records_all_without_warnings(pg, caplog):
    from conclave.infrastructure.postgres.schema import initialize_schema
    with caplog.at_level(logging.INFO, logger="conclave.migrations"):
        initialize_schema(pg)
        initialize_schema(pg)
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
    assert _applied(pg) == {m.id for m in MIGRATIONS}


def test_failing_migration_is_rolled_back_and_aborts(pg):
    from conclave.infrastructure.postgres.schema import initialize_schema
    initialize_schema(pg)
    broken = [
        Migration(id="900_broken", description="zweite Anweisung scheitert",
                  statements=("CREATE TABLE r1_a (x INTEGER)", "INSERT INTO gibt_es_nicht VALUES (1)")),
        Migration(id="901_after", description="darf nicht laufen", statements=("CREATE TABLE r1_b (x INTEGER)",)),
    ]
    with pytest.raises(MigrationError, match="900_broken"):
        run_migrations(pg, is_postgres=True, migrations=broken)
    assert not _table_exists(pg, "r1_a") and not _table_exists(pg, "r1_b")
    assert not {"900_broken", "901_after"} & _applied(pg)
    assert pg.get_transaction_status() == psycopg2.extensions.TRANSACTION_STATUS_IDLE



def test_without_autocommit_the_failing_migration_is_rolled_back_too(pg):
    """Review R1: auch eine Verbindung ohne Autocommit (Transaktion implizit) bleibt sauber."""
    from conclave.infrastructure.postgres.schema import initialize_schema
    initialize_schema(pg)
    pg.autocommit = False
    broken = [Migration(id="900_broken", description="zweite Anweisung scheitert",
                        statements=("CREATE TABLE r1_a (x INTEGER)", "INSERT INTO gibt_es_nicht VALUES (1)"))]
    with pytest.raises(MigrationError, match="900_broken"):
        run_migrations(pg, is_postgres=True, migrations=broken)
    pg.autocommit = True
    assert not _table_exists(pg, "r1_a") and "900_broken" not in _applied(pg)
