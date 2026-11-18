"""T2: Board unter PostgreSQL mit mehreren gleichzeitigen Nutzern (Verbindungspool).

Laeuft nur mit CONCLAVE_TEST_POSTGRES_DSN (CI-Job "postgres"); lokal sonst uebersprungen.
Abnahme conclave#70:
- 20 parallele Clients ohne Fehler und ohne verlorene Aenderungen
- zwei Server-Instanzen starten gleichzeitig ohne doppelte Migration
- next_task: zwei Agenten, ein Ticket -> nur einer bekommt es
"""

import os
import threading

import pytest

DSN = os.environ.get("CONCLAVE_TEST_POSTGRES_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="CONCLAVE_TEST_POSTGRES_DSN nicht gesetzt")

psycopg2 = pytest.importorskip("psycopg2")

from conclave_board.application.board import BoardService  # noqa: E402
from conclave_board.domain.board import Project, Task, TaskComment  # noqa: E402
from conclave_board.domain.principal import AGENT_PRINCIPAL, HUMAN_PRINCIPAL  # noqa: E402
from conclave_board.infrastructure.migrations import run_board_migrations  # noqa: E402
from conclave_board.infrastructure.postgres.board_repository import PostgresBoardRepository  # noqa: E402
from conclave_board.infrastructure.postgres.pool import ConnectionPool, PooledConnection  # noqa: E402

CLIENTS = 20


def _raw():
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    return conn


@pytest.fixture
def fresh_schema():
    conn = _raw()
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE")
        cur.execute("CREATE SCHEMA public")
    conn.close()


@pytest.fixture
def pooled(fresh_schema):
    with _raw() as setup:
        run_board_migrations(setup, is_postgres=True)
    pool = ConnectionPool(DSN, size=8)
    yield PooledConnection(pool)
    pool.close()


@pytest.fixture
def repo(pooled, crypto):
    repo = PostgresBoardRepository(pooled, crypto)
    project = Project.create("api", "API")
    repo.create_project(project)
    repo.project = project
    return repo


def _parallel(work, n=CLIENTS):
    errors, barrier = [], threading.Barrier(n)

    def run(i):
        try:
            barrier.wait(30)
            work(i)
        except Exception as e:  # noqa: BLE001 - im Test sammeln
            errors.append(e)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(120)
    assert errors == []


def test_twenty_clients_create_tasks_without_duplicate_numbers(repo):
    _parallel(lambda i: [repo.create_task(Task.create(repo.project, f"T{i}-{k}", "todo")) for k in range(10)])
    numbers = sorted(t.number for t in repo.list_tasks("api"))
    assert numbers == list(range(1, CLIENTS * 10 + 1))


def test_twenty_clients_comment_without_losing_one(repo):
    task = repo.create_task(Task.create(repo.project, "Viele Kommentare", "todo"))
    _parallel(lambda i: [repo.add_comment(TaskComment.create(task.id, f"{i}-{k}", "agent", actor_id="agent"))
                         for k in range(10)])
    comments = repo.list_comments(task.id)
    assert len(comments) == CLIENTS * 10
    assert len({c.body for c in comments}) == CLIENTS * 10


def test_check_then_write_under_the_row_lock_loses_no_update(repo):
    """Lesen, pruefen, schreiben unter FOR UPDATE: 20 Clients x 10 Erhoehungen ergeben 200."""
    task = repo.create_task(Task.create(repo.project, "Zaehler", "todo"))

    def work(_i):
        for _ in range(10):
            with repo.locked_task(task.id) as exists:
                assert exists
                value = int(repo.get_setting("zaehler") or 0)
                repo.set_setting("zaehler", str(value + 1))

    _parallel(work)
    assert repo.get_setting("zaehler") == str(CLIENTS * 10)


def test_without_the_lock_updates_get_lost(repo):
    """Gegenprobe: dieselbe Arbeit ohne Sperre verliert Erhoehungen (zeigt, dass der Test etwas misst)."""
    import time

    def work(_i):
        for _ in range(10):
            value = int(repo.get_setting("ohne") or 0)
            time.sleep(0.001)
            repo.set_setting("ohne", str(value + 1))

    _parallel(work)
    assert int(repo.get_setting("ohne")) < CLIENTS * 10


def test_a_failing_rule_rolls_back_everything_in_the_lock(repo):
    task = repo.create_task(Task.create(repo.project, "Regel", "todo"))
    with pytest.raises(RuntimeError):
        with repo.locked_task(task.id):
            repo.add_comment(TaskComment.create(task.id, "halb", "agent", actor_id="agent"))
            raise RuntimeError("Vier-Augen-Prinzip verletzt")
    assert repo.list_comments(task.id) == []


def test_two_agents_one_ticket_next_task_hands_it_out_once(repo):
    board = BoardService(repo)
    for round_ in range(10):
        board.create_task(HUMAN_PRINCIPAL, "api", f"Einzelticket {round_}")
        got = []
        _parallel(lambda i: got.append(board.next_task(AGENT_PRINCIPAL, "api")), n=2)
        assert len([t for t in got if t is not None]) == 1, round_


def test_two_server_instances_start_together_without_double_migration(fresh_schema):
    """Zwei Personal-Starts gleichzeitig auf leerer Datenbank: Advisory-Sperre, jede Migration einmal."""
    from conclave.infrastructure.migrations import MIGRATIONS
    from conclave.infrastructure.postgres.schema import initialize_schema
    from conclave_board.infrastructure.migrations import BOARD_MIGRATIONS

    def start(_i):
        conn = _raw()
        try:
            initialize_schema(conn)
        finally:
            conn.close()

    _parallel(start, n=2)
    conn = _raw()
    with conn.cursor() as cur:
        cur.execute("SELECT id, COUNT(*) FROM _migrations GROUP BY id")
        personal = dict(cur.fetchall())
        cur.execute("SELECT id, COUNT(*) FROM board_migrations GROUP BY id")
        board = dict(cur.fetchall())
    conn.close()
    assert set(personal) == {m.id for m in MIGRATIONS} and set(personal.values()) == {1}
    assert set(board) == {m.id for m in BOARD_MIGRATIONS} and set(board.values()) == {1}


def test_small_pool_serves_many_clients_by_waiting(fresh_schema, crypto):
    with _raw() as setup:
        run_board_migrations(setup, is_postgres=True)
    pool = ConnectionPool(DSN, size=2, timeout=60)
    try:
        repo = PostgresBoardRepository(PooledConnection(pool), crypto)
        project = Project.create("eng", "Eng")
        repo.create_project(project)
        _parallel(lambda i: repo.create_task(Task.create(project, f"T{i}", "todo")))
        assert len(repo.list_tasks("eng")) == CLIENTS
    finally:
        pool.close()


def test_personal_repositories_work_over_the_pool(fresh_schema, crypto):
    """Personal nutzt denselben Pool (api/server.py): parallele Conversations ohne Fehler."""
    from conclave.domain.conversation import Conversation
    from conclave.infrastructure.postgres.conversation_repository import PostgresConversationRepository
    from conclave.infrastructure.postgres.schema import initialize_schema

    with _raw() as setup:
        initialize_schema(setup)
    pool = ConnectionPool(DSN, size=4)
    try:
        conversations = PostgresConversationRepository(PooledConnection(pool))
        _parallel(lambda i: conversations.save(Conversation.create(topic=f"C{i}")))
        assert len(conversations.list_all()) == CLIENTS
    finally:
        pool.close()


def test_scoped_change_token_and_status_since_on_postgres(repo):
    """T5-Review: change_token_for und status_since_many mit Postgres-Platzhaltern."""
    from conclave_board.application.board import BoardService
    from conclave_board.domain.principal import Principal
    web = Project.create("web", "Web")
    repo.create_project(web)
    board = BoardService(repo)
    board.create_task(HUMAN_PRINCIPAL, "api", "hier")
    taken = board.next_task(Principal("agent"), "api")              # vor der Pause "alle"
    scoped = Principal("agent", actor_id="agent", projects=frozenset({"api"}))
    before = board.change_token_for(scoped)
    board.create_task(HUMAN_PRINCIPAL, "web", "dort")
    assert board.change_token_for(scoped) == before
    board.create_task(HUMAN_PRINCIPAL, "web", "Pause alle", kind="control", control="pause", scope="all")
    assert board.change_token_for(scoped) > before
    since = repo.status_since_many([taken.id])
    assert since[taken.id] is not None and board.status_since(taken) == since[taken.id]
