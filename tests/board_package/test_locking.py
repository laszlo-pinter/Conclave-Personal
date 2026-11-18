"""T2: Transaktionen und Sperre "erst pruefen, dann schreiben" im SQLite-Repository.

Gegenstueck zu den PostgreSQL-Tests (tests/persistence/test_postgres_concurrency.py).
"""

import threading

import pytest

from conclave_board.domain.board import Project, Task
from conclave_board.infrastructure.migrations import run_board_migrations
from conclave_board.infrastructure.sqlite.board_repository import SQLiteBoardRepository
from conclave_board.infrastructure.sqlite.connection import ThreadLocalConnection


def _repo(path, busy_timeout_ms: int | None = None):
    conn = ThreadLocalConnection(path, **({"busy_timeout_ms": busy_timeout_ms} if busy_timeout_ms else {}))
    run_board_migrations(conn)
    repo = SQLiteBoardRepository(conn, autocommit=True)
    project = Project.create("api", "API")
    repo.create_project(project)
    repo.task = repo.create_task(Task.create(project, "Erstes", "todo"))
    return repo


@pytest.fixture
def repo(tmp_path):
    return _repo(tmp_path / "board.db")


def test_check_then_write_under_the_lock_loses_no_update(tmp_path):
    """8 Threads lesen einen Zaehler und schreiben +1; mit Sperre geht keine Erhoehung verloren.

    SQLite vergibt die Schreibsperre nicht fair: Auf einem langsamen Rechner kann ein Thread bei
    starkem Andrang laenger als ``busy_timeout`` warten und bricht dann mit "database is locked" ab
    (#100). Das ist kein verlorenes Update, sondern ein sichtbarer Fehler. Der Test prueft die Sperre,
    nicht die Wartezeit: lange Wartezeit, und jede erfolgreiche Erhoehung muss im Zaehler stehen."""
    repo = _repo(tmp_path / "board.db", busy_timeout_ms=120_000)
    done, errors = [], []

    def work():
        for _ in range(10):
            try:
                with repo.locked_task(repo.task.id) as exists:
                    assert exists
                    value = int(repo.get_setting("zaehler") or 0)
                    repo.set_setting("zaehler", str(value + 1))
            except Exception as e:  # noqa: BLE001 - im Test sichtbar machen statt im Thread verlieren
                errors.append(repr(e))
                continue
            done.append(1)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(300)
    assert int(repo.get_setting("zaehler")) == len(done)                    # nichts still verloren
    assert errors == [] and len(done) == 80


def test_a_lock_that_times_out_raises_and_writes_nothing(tmp_path):
    """#100: Laeuft das Warten auf die Sperre ab, gibt es eine Ausnahme und keinen halben Schreibvorgang."""
    import sqlite3
    holder = _repo(tmp_path / "board.db")
    waiting = SQLiteBoardRepository(ThreadLocalConnection(tmp_path / "board.db", busy_timeout_ms=200), autocommit=True)
    holder.set_setting("zaehler", "1")
    entered, release = threading.Event(), threading.Event()

    def hold():
        with holder.locked_task(holder.task.id):
            entered.set()
            release.wait(10)

    thread = threading.Thread(target=hold)
    thread.start()
    try:
        assert entered.wait(10)
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            with waiting.locked_task(holder.task.id):
                waiting.set_setting("zaehler", "99")
    finally:
        release.set()
        thread.join(10)
    assert holder.get_setting("zaehler") == "1"
    with waiting.locked_task(holder.task.id):                                # danach geht es wieder
        waiting.set_setting("zaehler", "2")
    assert holder.get_setting("zaehler") == "2"


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
