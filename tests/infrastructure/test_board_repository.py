"""B1: Board-Domain und SQLite-Repository (Plan board.md)."""

import sqlite3
import threading

import pytest

from conclave.domain.board import (
    EVENT_VALUE_MAX,
    Project,
    StatusFlow,
    Task,
    TaskComment,
    TaskEvent,
    event_value,
    parse_ref,
)
from conclave.infrastructure.migrations import run_migrations
from conclave.infrastructure.sqlite.board_repository import POSITION_STEP, SQLiteBoardRepository
from conclave.infrastructure.sqlite.connection import ThreadLocalConnection
from conclave.infrastructure.sqlite.schema import initialize_schema


# ── Domain ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ref, expected", [("api#12", ("api", 12)), ("my-proj#1", ("my-proj", 1))])
def test_parse_ref(ref, expected):
    assert parse_ref(ref) == expected


@pytest.mark.parametrize("ref", ["API#1", "api#0", "api#12\n", " api#1", "api#", "#3", "api#1x", "a" * 41 + "#1", None])
def test_parse_ref_rejects(ref):
    with pytest.raises(ValueError):
        parse_ref(ref)


def test_status_flow():
    flow = StatusFlow()
    assert (flow.first, flow.second, flow.last) == ("todo", "doing", "done")
    with pytest.raises(ValueError):
        flow.check("fertig")
    with pytest.raises(ValueError):
        StatusFlow(("todo",))
    with pytest.raises(ValueError):
        StatusFlow(("todo", "todo"))


def test_project_and_comment_validation():
    with pytest.raises(ValueError):
        Project.create("Mit Leerzeichen", "X")
    with pytest.raises(ValueError):
        TaskComment.create("t", "text", origin="laszlo")         # nur human/agent/system/None
    assert TaskComment.create("t", "text", origin=None).origin is None


def test_event_value_hashes_long_text():
    assert event_value("kurz") == "kurz"
    long = "x" * (EVENT_VALUE_MAX + 1)
    value = event_value(long)
    assert value.startswith("sha256:") and len(value) < len(long)
    with pytest.raises(ValueError):
        TaskEvent.create("t", "tags", "a", "b", "human")           # nur verfolgte Felder


def test_task_tags_are_deduplicated_and_trimmed():
    p = Project.create("api", "API")
    assert Task.create(p, "T", "todo", tags=[" a ", "b", "a", ""]).tags == ("a", "b")


# ── Repository ────────────────────────────────────────────────────────────

@pytest.fixture
def repo(crypto):
    conn = sqlite3.connect(":memory:")
    initialize_schema(conn)
    r = SQLiteBoardRepository(conn, crypto, autocommit=True)
    r.conn = conn
    return r


def _project(repo, slug="api"):
    p = Project.create(slug, slug.upper())
    repo.create_project(p)
    return p


def test_numbers_are_per_project_and_sequential(repo):
    api, web = _project(repo, "api"), _project(repo, "web")
    refs = [repo.create_task(Task.create(api, f"A{i}", "todo")).ref for i in range(3)]
    refs.append(repo.create_task(Task.create(web, "W", "todo")).ref)
    assert refs == ["api#1", "api#2", "api#3", "web#1"]


def test_roundtrip_task_comment_event(repo):
    p = _project(repo)
    t = repo.create_task(Task.create(p, "Titel", "todo", description="# Beschreibung", tags=["ui", "bug"],
                                     human=True))
    loaded = repo.get_task("api", t.number)
    assert (loaded.title, loaded.description, loaded.tags, loaded.human, loaded.assignee) == (
        "Titel", "# Beschreibung", ("ui", "bug"), True, None)
    assert repo.get_task_by_id(t.id).ref == "api#1"

    c = TaskComment.create(t.id, "Kommentar", "agent", actor_id="agent", author_name="cc")
    repo.add_comment(c)
    repo.add_event(TaskEvent.create(t.id, "status", "todo", "doing", "agent", actor_id="agent"))
    [lc] = repo.list_comments(t.id)
    [le] = repo.list_events(t.id)
    assert (lc.body, lc.origin, lc.actor_id, lc.author_name) == ("Kommentar", "agent", "agent", "cc")
    assert (le.field_name, le.old_value, le.new_value, le.origin) == ("status", "todo", "doing", "agent")


def test_free_text_is_encrypted_at_rest(repo):
    p = _project(repo)
    t = repo.create_task(Task.create(p, "GEHEIMTITEL", "todo", description="GEHEIMBESCHREIBUNG", tags=["GEHEIMTAG"]))
    repo.add_comment(TaskComment.create(t.id, "GEHEIMKOMMENTAR", "human"))
    repo.add_event(TaskEvent.create(t.id, "title", "GEHEIMALT", "GEHEIMNEU", "human"))
    dump = "\n".join(repo.conn.iterdump())
    assert "GEHEIM" not in dump
    assert repo.get_task("api", 1).title == "GEHEIMTITEL"


def test_list_tasks_filters(repo):
    api, web = _project(repo, "api"), _project(repo, "web")
    repo.create_task(Task.create(api, "a", "todo"))
    repo.create_task(Task.create(api, "b", "done"))
    repo.create_task(Task.create(web, "c", "todo"))
    assert [t.ref for t in repo.list_tasks("api", ["todo"])] == ["api#1"]
    assert len(repo.list_tasks(statuses=["todo"])) == 2
    assert repo.list_tasks("api", []) == []
    assert len(repo.list_tasks()) == 3


def test_claim_is_atomic(repo):
    p = _project(repo)
    t = repo.create_task(Task.create(p, "a", "todo"))
    when = t.updated_at
    assert repo.claim_task(t.id, "todo", "doing", 1.0, when) is True
    assert repo.claim_task(t.id, "todo", "doing", 1.0, when) is False
    assert repo.get_task("api", 1).status == "doing"


def test_update_and_delete(repo):
    p = _project(repo)
    t = repo.create_task(Task.create(p, "a", "todo"))
    t.title, t.status, t.assignee = "neu", "review", "laszlo"
    assert repo.update_task(t)
    loaded = repo.get_task("api", 1)
    assert (loaded.title, loaded.status, loaded.assignee) == ("neu", "review", "laszlo")
    c = TaskComment.create(t.id, "x", "human")
    repo.add_comment(c)
    c.body = "y"
    assert repo.update_comment(c) and repo.get_comment(c.id).body == "y"
    assert repo.delete_comment(c.id) and repo.get_comment(c.id) is None
    repo.add_comment(TaskComment.create(t.id, "bleibt nicht", "human"))
    repo.add_event(TaskEvent.create(t.id, "status", "todo", "review", "human"))
    assert repo.delete_task(t.id) and repo.get_task("api", 1) is None
    assert repo.list_comments(t.id) == [] and repo.list_events(t.id) == []


def test_numbers_are_not_reused_after_delete(repo):
    p = _project(repo)
    t = repo.create_task(Task.create(p, "a", "todo"))
    repo.delete_task(t.id)
    assert repo.create_task(Task.create(p, "b", "todo")).ref == "api#2"


def test_project_rename_and_delete(repo):
    p = _project(repo)
    t = repo.create_task(Task.create(p, "a", "todo"))
    repo.add_comment(TaskComment.create(t.id, "x", "human"))
    assert repo.rename_project("api", "Neue API") and repo.get_project("api").name == "Neue API"
    assert repo.delete_project("api")
    assert repo.get_project("api") is None and repo.list_tasks() == []
    assert repo.delete_project("api") is False


def test_duplicate_slug_is_rejected(repo):
    _project(repo)
    with pytest.raises(sqlite3.IntegrityError):
        _project(repo)


def test_change_token_grows_with_every_write(repo):
    start = repo.change_token()
    p = _project(repo)
    t = repo.create_task(Task.create(p, "a", "todo"))
    repo.add_comment(TaskComment.create(t.id, "x", "human"))
    t.title = "b"
    repo.update_task(t)
    assert repo.change_token() == start + 4
    assert repo.claim_task(t.id, "doing", "review", 1.0, t.updated_at) is False
    assert repo.change_token() == start + 4                    # nichts geaendert, kein Anstieg


def test_renumber_after_many_insertions_at_the_same_place(repo):
    """Einfuegen immer zwischen die ersten beiden Karten, bis der Abstand nicht mehr reicht."""
    p = _project(repo)
    first = repo.create_task(Task.create(p, "erste", "todo", position=POSITION_STEP))
    repo.create_task(Task.create(p, "zweite", "todo", position=2 * POSITION_STEP))
    low, high = POSITION_STEP, 2 * POSITION_STEP
    for i in range(80):                                         # Halbierung: nach ~50 Schritten erschoepft
        middle = (low + high) / 2
        repo.create_task(Task.create(p, f"neu{i}", "todo", position=middle))
        high = middle
    positions = [pos for _, pos in repo.column_positions(p.id, "todo")]
    assert len(set(positions)) < len(positions)                 # die Genauigkeit ist ausgeschoepft
    order_before = [tid for tid, _ in repo.column_positions(p.id, "todo")]
    repo.renumber_column(p.id, "todo")
    after = repo.column_positions(p.id, "todo")
    assert [tid for tid, _ in after] == order_before            # Reihenfolge bleibt
    assert [pos for _, pos in after] == [POSITION_STEP * (i + 1) for i in range(len(after))]
    assert after[0][0] == first.id


def test_parallel_numbering_from_many_threads(tmp_path, crypto):
    """Mehrere Threads (je eigene Verbindung) legen gleichzeitig Tickets an: keine doppelten Nummern."""
    conn = ThreadLocalConnection(tmp_path / "board.db")
    initialize_schema(conn)
    conn.commit()
    setup = SQLiteBoardRepository(conn, crypto, autocommit=True)
    p = Project.create("api", "API")
    setup.create_project(p)
    barrier = threading.Barrier(8)
    errors = []

    def worker():
        repo = SQLiteBoardRepository(conn, crypto, autocommit=True)
        barrier.wait()
        try:
            for i in range(10):
                repo.create_task(Task.create(p, f"t{i}", "todo"))
        except Exception as e:                                  # pragma: no cover - Fehlerfall
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    numbers = sorted(t.number for t in setup.list_tasks("api"))
    assert numbers == list(range(1, 81))


def test_migration_is_recorded_once(tmp_path):
    conn = sqlite3.connect(":memory:")
    initialize_schema(conn)
    assert conn.execute("SELECT id FROM _migrations WHERE id = '012_board'").fetchone()
    assert "012_board" not in run_migrations(conn)
    assert conn.execute("SELECT value FROM board_meta WHERE key = 'changes'").fetchone() == (0,)
