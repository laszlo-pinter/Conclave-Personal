"""B1: Board-Repository gegen ein echtes PostgreSQL.

Laeuft nur mit CONCLAVE_TEST_POSTGRES_DSN (CI-Job "postgres"); lokal sonst
uebersprungen. Kernfall: parallele Nummernvergabe ueber mehrere Verbindungen
(unter READ COMMITTED wuerde MAX(number)+1 doppelte Nummern liefern).
"""

import os
import threading

import pytest

DSN = os.environ.get("CONCLAVE_TEST_POSTGRES_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="CONCLAVE_TEST_POSTGRES_DSN nicht gesetzt")

psycopg2 = pytest.importorskip("psycopg2")

from conclave.domain.board import Project, Task, TaskComment, TaskEvent  # noqa: E402


def _connect():
    conn = psycopg2.connect(DSN)
    conn.autocommit = True                       # wie im Server (api/server.py)
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


@pytest.fixture
def repo(pg, crypto):
    from conclave.infrastructure.postgres.board_repository import PostgresBoardRepository
    return PostgresBoardRepository(pg, crypto)


def test_roundtrip_and_encryption(repo, pg):
    p = Project.create("api", "API")
    repo.create_project(p)
    t = repo.create_task(Task.create(p, "GEHEIMTITEL", "todo", description="GEHEIM", tags=["x"], human=True))
    repo.add_comment(TaskComment.create(t.id, "GEHEIMKOMMENTAR", "agent", actor_id="agent"))
    repo.add_event(TaskEvent.create(t.id, "human", None, True, "agent", actor_id="agent"))
    loaded = repo.get_task("api", 1)
    assert (loaded.ref, loaded.title, loaded.human, loaded.tags) == ("api#1", "GEHEIMTITEL", True, ("x",))
    assert repo.list_comments(t.id)[0].origin == "agent"
    assert repo.list_events(t.id)[0].new_value == "True"
    with pg.cursor() as cur:
        cur.execute("SELECT title, description FROM board_tasks")
        title, description = cur.fetchone()
    assert "GEHEIM" not in title and "GEHEIM" not in description


def test_parallel_numbering_over_many_connections(repo, crypto):
    from conclave.infrastructure.postgres.board_repository import PostgresBoardRepository

    p = Project.create("api", "API")
    repo.create_project(p)
    barrier = threading.Barrier(8)
    errors = []

    def worker():
        conn = _connect()
        r = PostgresBoardRepository(conn, crypto)
        barrier.wait()
        try:
            for i in range(10):
                r.create_task(Task.create(p, f"t{i}", "todo"))
        except Exception as e:                    # pragma: no cover - Fehlerfall
            errors.append(e)
        finally:
            conn.close()

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert sorted(t.number for t in repo.list_tasks("api")) == list(range(1, 81))


def test_claim_race_over_many_connections(repo, crypto):
    from conclave.infrastructure.postgres.board_repository import PostgresBoardRepository

    p = Project.create("api", "API")
    repo.create_project(p)
    t = repo.create_task(Task.create(p, "a", "todo"))
    barrier = threading.Barrier(6)
    results = []

    def grab():
        conn = _connect()
        barrier.wait()
        results.append(PostgresBoardRepository(conn, crypto).claim_task(t.id, "todo", "doing", 1.0, t.updated_at))
        conn.close()

    threads = [threading.Thread(target=grab) for _ in range(6)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert results.count(True) == 1


def test_renumber_keeps_order(repo):
    p = Project.create("api", "API")
    repo.create_project(p)
    ids = [repo.create_task(Task.create(p, f"t{i}", "todo", position=pos)).id
           for i, pos in enumerate([5.0, 5.0, 1.0, 3.0])]
    before = [tid for tid, _ in repo.column_positions(p.id, "todo")]
    repo.renumber_column(p.id, "todo")
    after = repo.column_positions(p.id, "todo")
    assert [tid for tid, _ in after] == before
    assert [pos for _, pos in after] == [1024.0, 2048.0, 3072.0, 4096.0]
    assert before[0] == ids[2]


def test_delete_project_respects_foreign_keys(repo):
    p = Project.create("api", "API")
    repo.create_project(p)
    t = repo.create_task(Task.create(p, "a", "todo"))
    repo.add_comment(TaskComment.create(t.id, "x", "human"))
    repo.add_event(TaskEvent.create(t.id, "status", "todo", "doing", "human"))
    assert repo.delete_project("api")
    assert repo.list_projects() == []


def test_migration_012_is_idempotent(pg):
    from conclave.infrastructure.migrations import run_migrations
    with pg.cursor() as cur:
        cur.execute("SELECT id FROM _migrations WHERE id = '012_board'")
        assert cur.fetchone() is not None
    assert "012_board" not in run_migrations(pg, is_postgres=True)
