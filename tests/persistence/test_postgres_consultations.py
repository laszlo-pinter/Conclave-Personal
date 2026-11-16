"""R10 (conclave#45): Consultations auf PostgreSQL - atomares Limit, Uebergaenge, Lease.

Laeuft nur mit ``CONCLAVE_TEST_POSTGRES_DSN`` (wie test_postgres_board.py).
"""

import os
import threading
from datetime import UTC, datetime, timedelta

import pytest

DSN = os.environ.get("CONCLAVE_TEST_POSTGRES_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="CONCLAVE_TEST_POSTGRES_DSN nicht gesetzt")

psycopg2 = pytest.importorskip("psycopg2")

from conclave.domain.consultation import DONE, INTERRUPTED, RUNNING, Consultation  # noqa: E402


def _connect():
    conn = psycopg2.connect(DSN)
    conn.autocommit = True                       # wie im Server
    return conn


@pytest.fixture
def pg():
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE")
        cur.execute("CREATE SCHEMA public")
    from conclave.infrastructure.postgres.schema import initialize_schema
    initialize_schema(conn)
    yield conn
    conn.close()


def _repo(conn):
    from conclave.infrastructure.postgres.consultation_repository import PostgresConsultationRepository
    return PostgresConsultationRepository(conn)


def _new(channel="agent"):
    return Consultation.create(source="board", source_ref="api#12", question="?", reviewers=["gpt"],
                               channel=channel)


def test_limit_holds_across_connections(pg):
    """Wie mehrere Server-Prozesse: jede Anfrage mit eigener Verbindung, gleichzeitig."""
    since = datetime.now(UTC) - timedelta(hours=1)
    results, barrier = [], threading.Barrier(8)
    conns = [_connect() for _ in range(8)]

    def attempt(conn):
        barrier.wait()
        results.append(_repo(conn).create_if_under_limit(_new(), since, 3))

    threads = [threading.Thread(target=attempt, args=(c,)) for c in conns]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for c in conns:
        c.close()
    assert results.count(True) == 3
    assert _repo(pg).count_since("board", "api#12", since, channel="agent") == 3


def test_limit_holds_for_threads_sharing_one_connection(pg):
    repo = _repo(pg)
    since = datetime.now(UTC) - timedelta(hours=1)
    results, barrier = [], threading.Barrier(8)

    def attempt():
        barrier.wait()
        results.append(repo.create_if_under_limit(_new(), since, 2))

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 2
    assert repo.create_if_under_limit(_new(channel="human"), since, 2)          # eigenes Kontingent


def test_transition_and_lease_on_postgres(pg):
    repo = _repo(pg)
    c = _new()
    assert repo.create_if_under_limit(c, datetime.now(UTC) - timedelta(hours=1), 5)
    assert repo.claim(c.id, owner="w1", lease_until=datetime.now(UTC) - timedelta(seconds=1))
    assert [x.id for x in repo.list_expired_running(datetime.now(UTC))] == [c.id]
    assert repo.renew_lease(c.id, "w1", datetime.now(UTC) + timedelta(minutes=2))
    assert not repo.renew_lease(c.id, "fremd", datetime.now(UTC) + timedelta(minutes=2))
    assert repo.list_expired_running(datetime.now(UTC)) == []
    running = repo.get(c.id)
    assert (running.status, running.owner) == (RUNNING, "w1")
    assert repo.transition(running, RUNNING, INTERRUPTED, error="weg")
    assert not repo.transition(running, RUNNING, DONE)
    assert repo.get(c.id).status == INTERRUPTED
    repo.set_conversation(c.id, "conv-1")
    assert (repo.get(c.id).conversation_id, repo.get(c.id).status) == ("conv-1", INTERRUPTED)
