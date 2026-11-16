"""P2 (conclave#57): Vorhaben auf PostgreSQL - lueckenlose Nummern ueber mehrere Verbindungen.

Laeuft nur mit ``CONCLAVE_TEST_POSTGRES_DSN`` (wie test_postgres_board.py).
"""

import os
import threading

import pytest

DSN = os.environ.get("CONCLAVE_TEST_POSTGRES_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="CONCLAVE_TEST_POSTGRES_DSN nicht gesetzt")

psycopg2 = pytest.importorskip("psycopg2")

from conclave.application.board import BoardService  # noqa: E402
from conclave.domain.principal import AGENT_PRINCIPAL as AGENT  # noqa: E402
from conclave.domain.principal import HUMAN_PRINCIPAL as HUMAN  # noqa: E402


def _connect():
    conn = psycopg2.connect(DSN)
    conn.autocommit = True                       # wie im Server
    return conn


def _service(conn, crypto):
    from conclave.infrastructure.postgres.board_repository import PostgresBoardRepository
    return BoardService(PostgresBoardRepository(conn, crypto))


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


def test_parallel_creates_in_an_initiative_are_gapless(pg, crypto):
    board = _service(pg, crypto)
    board.create_project(HUMAN, "conclave", "Conclave")
    board.create_initiative(HUMAN, "conclave", "sich", "Sicherheit")
    conns = [_connect() for _ in range(8)]
    barrier, errors = threading.Barrier(8), []

    def create(conn):
        try:
            svc = _service(conn, crypto)
            barrier.wait()
            for i in range(4):
                svc.create_task(AGENT, "conclave", f"T{i}", initiative="sich")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=create, args=(c,)) for c in conns]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for c in conns:
        c.close()
    assert errors == []
    tasks = board.list_tasks("conclave")
    assert sorted(t.initiative_number for t in tasks) == list(range(1, 33))
    assert sorted(t.number for t in tasks) == list(range(1, 33))


def test_references_assignment_and_history_on_postgres(pg, crypto):
    board = _service(pg, crypto)
    board.create_project(HUMAN, "conclave", "Conclave")
    board.create_initiative(HUMAN, "conclave", "sich", "Sicherheit")
    board.create_task(HUMAN, "conclave", "ohne")
    board.create_task(HUMAN, "conclave", "mit", initiative="sich")
    assert board.get_task("conclave/sich-1").ref == "conclave#2"
    moved = board.assign_initiative(HUMAN, "conclave#1", "sich")
    assert moved.initiative_ref == "conclave/sich-2"
    events = [e for e in board.history("conclave#1") if e.field_name == "initiative"]
    assert [(e.old_value, e.new_value) for e in events] == [(None, "conclave/sich-2")]
    stale = board.get_task("conclave#2")
    board.update_task(HUMAN, "conclave#2", title="geaendert")
    assert not board._repo.assign_initiative(stale, None, events[0])          # alte Version: nichts geaendert
    board.update_initiative(HUMAN, "conclave", "sich", title="Sicherheit v0.7", rank=-2)
    assert [i.title for i in board.list_initiatives("conclave")] == ["Sicherheit v0.7"]
    assert "initiative" in [e.field_name for e in board.project_history("conclave")]
