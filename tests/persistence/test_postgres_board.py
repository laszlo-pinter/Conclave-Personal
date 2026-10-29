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


def test_project_creation_is_atomic_and_deletes_cascade(repo, pg):
    p = Project.create("api", "API")
    repo.create_project(p)
    with pytest.raises(psycopg2.errors.UniqueViolation):
        repo.create_project(Project.create("api", "Doppelt"))             # Slug vergeben
    with pg.cursor() as cur:
        cur.execute("SELECT (SELECT count(*) FROM board_projects), (SELECT count(*) FROM board_counters)")
        assert cur.fetchone() == (1, 1)                                     # kein Projekt ohne Zaehler
        cur.execute("""
            SELECT tc.table_name, rc.delete_rule FROM information_schema.referential_constraints rc
            JOIN information_schema.table_constraints tc ON tc.constraint_name = rc.constraint_name
            WHERE tc.table_name LIKE 'board_%' ORDER BY 1""")
        rules = cur.fetchall()
    assert rules and all(rule == "CASCADE" for _, rule in rules)
    assert {t for t, _ in rules} == {"board_comments", "board_counters", "board_events", "board_tasks"}



# ── B2: Dienst gegen Postgres ─────────────────────────────────────────────

def _service(conn, crypto):
    from conclave.application.board import BoardService
    from conclave.infrastructure.postgres.board_repository import PostgresBoardRepository
    return BoardService(PostgresBoardRepository(conn, crypto))


def test_service_history_and_comment_order_on_postgres(pg, crypto):
    from conclave.domain.principal import AGENT_PRINCIPAL as AGENT
    from conclave.domain.principal import HUMAN_PRINCIPAL as HUMAN

    svc = _service(pg, crypto)
    svc.create_project(HUMAN, "api", "API")
    svc.create_task(HUMAN, "api", "T", description="alt")
    svc.update_task(AGENT, "api#1", title="T2", description="neu", status="doing", human=True)
    assert [e.field_name for e in svc.history("api#1")] == ["title", "description", "status", "human"]
    for i in range(10):
        svc.add_comment(HUMAN, "api#1", f"k{i}")
    assert [c.body for c in svc.comments("api#1")] == [f"k{i}" for i in range(10)]
    with pg.cursor() as cur:
        cur.execute("SELECT seq FROM board_events ORDER BY seq")
        seqs = [r[0] for r in cur.fetchall()]
    assert len(set(seqs)) == 4                                    # eindeutig, in einer Anweisung vergeben


def test_service_update_of_a_vanished_task_writes_no_history(pg, crypto):
    from conclave.domain.principal import HUMAN_PRINCIPAL as HUMAN

    svc = _service(pg, crypto)
    svc.create_project(HUMAN, "api", "API")
    task = svc.create_task(HUMAN, "api", "T")
    svc.delete_task(HUMAN, "api#1")
    from conclave.domain.board import TaskEvent
    assert svc._repo.update_task(task, [TaskEvent.create(task.id, "title", "T", "X", "human")]) is False
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM board_events")
        assert cur.fetchone() == (0,)


def test_parallel_next_task_over_many_connections(pg, crypto):
    from conclave.domain.principal import AGENT_PRINCIPAL as AGENT
    from conclave.domain.principal import HUMAN_PRINCIPAL as HUMAN

    setup = _service(pg, crypto)
    setup.create_project(HUMAN, "api", "API")
    for i in range(6):
        setup.create_task(HUMAN, "api", f"t{i}")
    setup.create_task(HUMAN, "api", "privat", human=True)
    barrier = threading.Barrier(8)
    got, errors = [], []

    def agent():
        conn = _connect()
        svc = _service(conn, crypto)
        barrier.wait()
        try:
            while (task := svc.next_task(AGENT, "api")) is not None:
                got.append(task.ref)
        except Exception as e:                                    # pragma: no cover
            errors.append(e)
        finally:
            conn.close()

    threads = [threading.Thread(target=agent) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert sorted(got) == [f"api#{i}" for i in range(1, 7)]
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM board_events WHERE field = 'status'")
        assert cur.fetchone() == (6,)                             # genau ein Eintrag je vergebenem Ticket


def test_optimistic_update_and_flag_guard_on_postgres(pg, crypto):
    from conclave.domain.board import TaskEvent
    from conclave.domain.principal import HUMAN_PRINCIPAL as HUMAN

    svc = _service(pg, crypto)
    svc.create_project(HUMAN, "api", "API")
    svc.create_task(HUMAN, "api", "T")
    repo = svc._repo
    stale = repo.get_task("api", 1)
    fresh = repo.get_task("api", 1)
    fresh.human = True
    assert repo.update_task(fresh) is True and fresh.version == 2
    stale.title = "harmlos"
    event = TaskEvent.create(stale.id, "title", "T", "harmlos", "agent")
    assert repo.update_task(stale, [event]) is False                    # veralteter Stand: nichts geschrieben
    assert repo.update_task(stale) is False
    now = repo.get_task("api", 1)
    assert (now.human, now.title, now.version) == (True, "T", 2)
    claim_event = TaskEvent.create(now.id, "status", "todo", "doing", "agent")
    assert repo.claim_task(now.id, "todo", "doing", 1.0, now.updated_at, claim_event) is False   # markiert
    assert repo.claim_task(now.id, "todo", "doing", 1.0, now.updated_at) is False
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM board_events")
        assert cur.fetchone() == (0,)



def test_agent_comment_guard_on_postgres(pg, crypto):
    from conclave.domain.board import TaskComment
    from conclave.domain.principal import HUMAN_PRINCIPAL as HUMAN

    svc = _service(pg, crypto)
    svc.create_project(HUMAN, "api", "API")
    task = svc.create_task(HUMAN, "api", "T", human=True)
    repo = svc._repo
    assert repo.add_comment_checked(TaskComment.create(task.id, "x", "agent"), only_if_not_human=True) is False
    assert repo.add_comment_checked(TaskComment.create(task.id, "y", "human")) is True
    assert [c.body for c in repo.list_comments(task.id)] == ["y"]
