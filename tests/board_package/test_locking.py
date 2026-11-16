"""T2: Transaktionen und Sperre "erst pruefen, dann schreiben" im SQLite-Repository.

Gegenstueck zu den PostgreSQL-Tests (tests/persistence/test_postgres_concurrency.py).
"""

import threading

import pytest

from conclave_board.domain.board import Project, Task
from conclave_board.infrastructure.migrations import run_board_migrations
from conclave_board.infrastructure.sqlite.board_repository import SQLiteBoardRepository
from conclave_board.infrastructure.sqlite.connection import ThreadLocalConnection


@pytest.fixture
def repo(tmp_path):
    conn = ThreadLocalConnection(tmp_path / "board.db")
    run_board_migrations(conn)
    repo = SQLiteBoardRepository(conn, autocommit=True)
    project = Project.create("api", "API")
    repo.create_project(project)
    repo.task = repo.create_task(Task.create(project, "Erstes", "todo"))
    return repo


def test_check_then_write_under_the_lock_loses_no_update(repo):
    """8 Threads lesen einen Zaehler und schreiben +1; mit Sperre geht keine Erhoehung verloren."""
    def work():
        for _ in range(10):
            with repo.locked_task(repo.task.id) as exists:
                assert exists
                value = int(repo.get_setting("zaehler") or 0)
                repo.set_setting("zaehler", str(value + 1))

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert repo.get_setting("zaehler") == "80"


def test_writes_inside_the_lock_commit_together_or_not_at_all(repo):
    with pytest.raises(RuntimeError):
        with repo.locked_task(repo.task.id):
            repo.set_setting("a", "1")
            repo.set_setting("b", "2")
            raise RuntimeError("Regel verletzt")
    assert repo.get_setting("a") is None and repo.get_setting("b") is None

    with repo.locked_task(repo.task.id):
        repo.set_setting("a", "1")
        repo.set_setting("b", "2")
    assert (repo.get_setting("a"), repo.get_setting("b")) == ("1", "2")


def test_missing_task_is_reported(repo):
    with repo.locked_task("gibt-es-nicht") as exists:
        assert exists is False


def test_plain_writes_still_commit_on_their_own(repo):
    repo.set_setting("x", "1")
    assert not repo._connection.in_transaction
    assert repo.get_setting("x") == "1"
