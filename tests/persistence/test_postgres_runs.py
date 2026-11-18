"""R11 (conclave#46): Herkunft der Laeufe und Token-Summen fuer die Budgets auf PostgreSQL."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

DSN = os.environ.get("CONCLAVE_TEST_POSTGRES_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="CONCLAVE_TEST_POSTGRES_DSN nicht gesetzt")

psycopg2 = pytest.importorskip("psycopg2")

from conclave.domain.run import Run, UsageRecord  # noqa: E402


@pytest.fixture
def pg():
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE")
        cur.execute("CREATE SCHEMA public")
    from conclave.infrastructure.postgres.schema import initialize_schema
    initialize_schema(conn)
    with conn.cursor() as cur:
        for cid in ("c1", "c2"):
            cur.execute("INSERT INTO conversations (id, topic, status, created_at) VALUES (%s, '', 'active', now())",
                        (cid,))
    yield conn
    conn.close()


def _run(conv, started, tokens, origin=None):
    return Run(id=str(uuid.uuid4()), conversation_id=conv, kind="invoke", participants=["m1"], started_at=started,
               finished_at=started, status="success", usage=UsageRecord("p", "m", tokens, 0), origin=origin)


def test_origin_and_token_sums_on_postgres(pg):
    from conclave.infrastructure.postgres.run_repository import PostgresRunRepository
    repo = PostgresRunRepository(pg)
    now = datetime.now(UTC)
    repo.save(_run("c1", now - timedelta(days=2), 1000, origin="agent"))  # aelter als 24 Stunden
    repo.save(_run("c1", now, 100, origin="agent"))
    repo.save(_run("c2", now, 50))
    since = now - timedelta(days=1)
    assert repo.tokens_since(since, origin="agent") == 100
    assert repo.tokens_since(since, origin="agent", conversation_id="c2") == 0
    assert repo.tokens_since(since) == 150


def test_origin_survives_the_roundtrip_on_postgres(pg):
    """#94 (P2): get und beide list-Abfragen liefern die gespeicherte Herkunft."""
    from conclave.infrastructure.postgres.run_repository import PostgresRunRepository
    repo = PostgresRunRepository(pg)
    now = datetime.now(UTC)
    agent, human = _run("c1", now, 10, origin="agent"), _run("c1", now - timedelta(seconds=1), 10)
    repo.save(agent)
    repo.save(human)
    assert repo.get(agent.id).origin == "agent" and repo.get(human.id).origin is None
    assert [r.origin for r in repo.list_by_conversation("c1")] == ["agent", None]
    assert [r.origin for r in repo.list_all()] == ["agent", None]
