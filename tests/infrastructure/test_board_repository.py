"""B1: Board-Domain und SQLite-Repository (Plan board.md)."""

import sqlite3
import threading

import pytest

from conclave.domain.board import (
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


def test_event_value_keeps_the_full_text():
    long = "Abnahme\n" + "x" * 5000 + "\n- Postgres geprueft"
    assert event_value(long) == long and event_value(True) == "True" and event_value(None) is None
    with pytest.raises(ValueError):
        TaskEvent.create("t", "assignee", "a", "b", "human")       # nur verfolgte Felder


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


def test_migration_is_recorded_once():
    conn = sqlite3.connect(":memory:")
    initialize_schema(conn)
    assert conn.execute("SELECT id FROM _migrations WHERE id = '012_board'").fetchone()
    assert "012_board" not in run_migrations(conn)
    assert conn.execute("SELECT value FROM board_meta WHERE key = 'changes'").fetchone() == (0,)


# ── Review B1: Fehlerpfade, CASCADE, Konfiguration ────────────────────────

def test_ref_before_saving_is_an_error():
    with pytest.raises(ValueError):
        Task.create(Project.create("api", "API"), "T", "todo").ref


def test_failed_write_is_rolled_back_and_releases_the_lock(tmp_path, crypto, monkeypatch):
    """Faellt das INSERT nach dem Zaehler-UPDATE aus, bleibt nichts halb stehen:
    der Zaehler ist zurueckgerollt und eine andere Verbindung kann sofort schreiben."""
    conn = ThreadLocalConnection(tmp_path / "board.db", busy_timeout_ms=500)
    initialize_schema(conn)
    conn.commit()
    repo = SQLiteBoardRepository(conn, crypto, autocommit=True)
    p = _project(repo)
    real = repo._execute

    def broken(sql, params=()):
        if sql.startswith("INSERT INTO board_tasks"):
            raise sqlite3.OperationalError("simulierter Ausfall")
        return real(sql, params)

    monkeypatch.setattr(repo, "_execute", broken)
    with pytest.raises(sqlite3.OperationalError):
        repo.create_task(Task.create(p, "faellt aus", "todo"))
    monkeypatch.setattr(repo, "_execute", real)

    other = sqlite3.connect(tmp_path / "board.db", timeout=0.5)       # haette sonst "database is locked"
    other.execute("UPDATE board_meta SET value = value WHERE key = 'changes'")
    other.commit()
    other.close()
    assert repo.create_task(Task.create(p, "klappt", "todo")).number == 1    # Zaehler nicht verbraucht


def test_delete_project_cascades_in_one_statement(repo):
    p = _project(repo)
    t = repo.create_task(Task.create(p, "a", "todo"))
    repo.add_comment(TaskComment.create(t.id, "x", "human"))
    repo.add_event(TaskEvent.create(t.id, "status", "todo", "doing", "human"))
    statements = []
    real = repo._execute
    repo._execute = lambda sql, params=(): (statements.append(sql), real(sql, params))[1]
    assert repo.delete_project("api")
    assert [s for s in statements if s.startswith("DELETE")] == ["DELETE FROM board_projects WHERE slug = ?"]
    for table in ("board_tasks", "board_comments", "board_events", "board_counters"):
        assert repo.conn.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,), table  # nosec B608


def test_board_statuses_from_config(tmp_path):
    from conclave.cli.config import ConclaveConfig
    cfg = tmp_path / "config.toml"
    cfg.write_text('[board]\nstatuses = ["backlog", "in-arbeit", "pruefen", "fertig"]\n', encoding="utf-8")
    assert ConclaveConfig.from_sources(cfg).board.statuses == ("backlog", "in-arbeit", "pruefen", "fertig")
    assert ConclaveConfig.from_sources(tmp_path / "fehlt.toml").board.statuses == ("todo", "doing", "review", "done")


@pytest.mark.parametrize("value", ['["nur-eine"]', '["a", "a"]', '"todo"', '["Mit Leerzeichen", "b"]', '[1, 2]',
                                   '[" todo", "done"]'])
def test_invalid_board_statuses_are_rejected(tmp_path, value):
    from conclave.cli.config import ConclaveConfig
    cfg = tmp_path / "config.toml"
    cfg.write_text(f"[board]\nstatuses = {value}\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"\[board\] statuses"):
        ConclaveConfig.from_sources(cfg)


@pytest.mark.parametrize("toml, env, expected", [
    ("", None, "internal"),                                                   # Standard: eigenes Board
    ('[kanzo]\nreviewers = ["gpt"]\n', None, "internal"),                     # Reviewer allein reichen nicht
    ('[kanzo]\nurl = "http://localhost:4242/mcp"\n', None, "kanzo"),          # Kanzo-Adresse gesetzt
    ("", "http://localhost:4242/mcp", "kanzo"),                               # ... oder per Umgebung
    ('[kanzo]\nurl = "http://localhost:4242/mcp"\n[board]\nsource = "internal"\n', None, "internal"),
    ('[board]\nsource = "kanzo"\n', None, "kanzo"),
])
def test_board_source_from_config(tmp_path, monkeypatch, toml, env, expected):
    """B6/E6: Consultations lesen aus dem eigenen Board, ausser Kanzo ist ausdruecklich eingestellt."""
    from conclave.cli.config import ConclaveConfig
    if env:
        monkeypatch.setenv("CONCLAVE_KANZO_URL", env)
    else:
        monkeypatch.delenv("CONCLAVE_KANZO_URL", raising=False)
    cfg = tmp_path / "config.toml"
    cfg.write_text(toml, encoding="utf-8")
    assert ConclaveConfig.from_sources(cfg).board.source == expected


@pytest.mark.parametrize("value", ['"extern"', '"Internal"', "1", '["internal"]'])
def test_invalid_board_source_is_rejected(tmp_path, value):
    from conclave.cli.config import ConclaveConfig
    cfg = tmp_path / "config.toml"
    cfg.write_text(f"[board]\nsource = {value}\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"\[board\] source"):
        ConclaveConfig.from_sources(cfg)


# ── B8: [consultations] statt [kanzo] fuer Reviewer und Grenzen ──────────

@pytest.mark.parametrize("toml, reviewers, legacy", [
    ('[consultations]\nreviewers = ["gpt"]\nmax_per_hour = 5\n', ("gpt",), ()),
    ('[kanzo]\nreviewers = ["alt"]\n', ("alt",), ("reviewers",)),                       # weiter gelesen
    ('[kanzo]\nreviewers = ["alt"]\n[consultations]\nreviewers = ["neu"]\n', ("neu",), ()),  # neu gewinnt
    ("", (), ()),
])
def test_consultation_settings_section(tmp_path, monkeypatch, toml, reviewers, legacy):
    from conclave.cli.config import ConclaveConfig
    monkeypatch.delenv("CONCLAVE_KANZO_URL", raising=False)
    cfg = tmp_path / "config.toml"
    cfg.write_text(toml, encoding="utf-8")
    kanzo = ConclaveConfig.from_sources(cfg).kanzo
    assert (kanzo.reviewers, kanzo.legacy_keys) == (reviewers, legacy)


def test_reviewers_alone_do_not_switch_the_source_to_kanzo(tmp_path, monkeypatch):
    from conclave.cli.config import ConclaveConfig
    monkeypatch.delenv("CONCLAVE_KANZO_URL", raising=False)
    cfg = tmp_path / "config.toml"
    cfg.write_text('[consultations]\nreviewers = ["gpt"]\n', encoding="utf-8")
    assert ConclaveConfig.from_sources(cfg).board.source == "internal"


@pytest.mark.parametrize("toml, message", [
    ('[consultations]\nreviewers = "gpt"\n', r"\[consultations\] reviewers"),
    ('[kanzo]\nmax_per_hour = 0\n', r"\[kanzo\] max_per_hour"),
    ('[consultations]\ncomment_max_chars = 10\n', r"\[consultations\] comment_max_chars"),
])
def test_invalid_consultation_settings_name_their_section(tmp_path, toml, message):
    from conclave.cli.config import ConclaveConfig
    cfg = tmp_path / "config.toml"
    cfg.write_text(toml, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        ConclaveConfig.from_sources(cfg)


def test_legacy_kanzo_keys_log_a_warning(tmp_path, monkeypatch, caplog):
    from conclave.api.server import _build_app
    from conclave.cli.config import ConclaveConfig, KanzoSettings
    for name, value in (("CONCLAVE_WORKSPACE", tmp_path / "ws"), ("CONCLAVE_SECRET_KEY_FILE", tmp_path / "k"),
                        ("CONCLAVE_API_TOKEN_FILE", tmp_path / "t"), ("CONCLAVE_AGENT_TOKEN_FILE", tmp_path / "a")):
        monkeypatch.setenv(name, str(value))
    monkeypatch.delenv("CONCLAVE_API_KEY", raising=False)
    monkeypatch.delenv("CONCLAVE_AGENT_KEY", raising=False)
    kanzo = KanzoSettings.from_section({"reviewers": ["gpt"]})
    with caplog.at_level("WARNING"):
        _build_app(ConclaveConfig(db_path=tmp_path / "c.db", kanzo=kanzo))
    assert any("[consultations]" in r.getMessage() and "reviewers" in r.getMessage() for r in caplog.records)


def test_key_in_both_sections_logs_that_kanzo_is_ignored(tmp_path, monkeypatch, caplog):
    from conclave.api.server import _build_app
    from conclave.cli.config import ConclaveConfig, KanzoSettings
    for name, value in (("CONCLAVE_WORKSPACE", tmp_path / "ws"), ("CONCLAVE_SECRET_KEY_FILE", tmp_path / "k"),
                        ("CONCLAVE_API_TOKEN_FILE", tmp_path / "t"), ("CONCLAVE_AGENT_TOKEN_FILE", tmp_path / "a")):
        monkeypatch.setenv(name, str(value))
    monkeypatch.delenv("CONCLAVE_API_KEY", raising=False)
    monkeypatch.delenv("CONCLAVE_AGENT_KEY", raising=False)
    kanzo = KanzoSettings.from_section({"reviewers": ["alt"]}, {"reviewers": ["neu"]})
    assert (kanzo.reviewers, kanzo.ignored_keys, kanzo.legacy_keys) == (("neu",), ("reviewers",), ())
    with caplog.at_level("WARNING"):
        _build_app(ConclaveConfig(db_path=tmp_path / "c.db", kanzo=kanzo))
    assert any("ignoriert" in r.getMessage() and "reviewers" in r.getMessage() for r in caplog.records)


def test_migration_014_takes_rank_from_position(tmp_path):
    """P1: bestehende Boards behalten ihre sichtbare Reihenfolge."""
    import sqlite3
    from conclave.infrastructure.migrations import MIGRATIONS, run_migrations
    conn = sqlite3.connect(tmp_path / "alt.db")
    before = [m for m in MIGRATIONS if m.id != "014_board_rank"]
    for table in ("conversations (id TEXT PRIMARY KEY, status TEXT)", "agents (id TEXT PRIMARY KEY)",
                  "audit_log (id TEXT PRIMARY KEY)", "messages (id TEXT PRIMARY KEY, content TEXT)"):
        conn.execute(f"CREATE TABLE {table}")
    run_migrations(conn, migrations=before)
    conn.execute("ALTER TABLE board_tasks DROP COLUMN rank")                # Stand vor P1 (012 ohne rank)
    conn.commit()
    conn.execute("INSERT INTO board_projects (id, slug, name, created_at) VALUES ('p', 'api', 'API', '2026')")
    for n, pos in ((1, 3072.0), (2, 1024.0), (3, 2048.0)):
        conn.execute("INSERT INTO board_tasks (id, project_id, number, title, status, position, human, created_at, "
                     "updated_at) VALUES (?, 'p', ?, 't', 'todo', ?, 0, '2026', '2026')", (f"t{n}", n, pos))
    conn.commit()
    run_migrations(conn)
    rows = conn.execute("SELECT number FROM board_tasks ORDER BY rank").fetchall()
    assert [r[0] for r in rows] == [2, 3, 1]


def test_migration_015_adds_origin_columns_and_history_tables(tmp_path, crypto):
    """R9: bestehende Boards bekommen Herkunftsspalten, Soft-Delete und Projekt-Verlauf."""
    import sqlite3
    from conclave.infrastructure.migrations import MIGRATIONS, run_migrations
    conn = sqlite3.connect(tmp_path / "alt.db")
    before = [m for m in MIGRATIONS if m.id != "015_board_history"]
    for table in ("conversations (id TEXT PRIMARY KEY, status TEXT)", "agents (id TEXT PRIMARY KEY)",
                  "audit_log (id TEXT PRIMARY KEY)", "messages (id TEXT PRIMARY KEY, content TEXT)"):
        conn.execute(f"CREATE TABLE {table}")
    run_migrations(conn, migrations=before)
    for table, column in (("board_tasks", "origin"), ("board_tasks", "actor_id"), ("board_tasks", "created_by"),
                          ("board_comments", "deleted_at")):
        conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")        # Stand vor R9
    conn.execute("DROP TABLE board_project_events")
    conn.execute("DROP TABLE board_settings")
    conn.execute("INSERT INTO board_projects (id, slug, name, created_at) VALUES ('p', 'api', 'API', '2026-01-01')")
    conn.execute("INSERT INTO board_tasks (id, project_id, number, title, status, position, human, created_at, "
                 "updated_at) VALUES ('t1', 'p', 1, 'alt', 'todo', 1024, 0, '2026-01-01', '2026-01-01')")
    conn.commit()
    run_migrations(conn)
    repo = SQLiteBoardRepository(conn, autocommit=True)
    task = repo.get_task("api", 1)
    assert (task.origin, task.actor_id, task.created_by) == (None, None, "")
    assert repo.list_project_events("p") == [] and repo.get_setting("last_status") is None
