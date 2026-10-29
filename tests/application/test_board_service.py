"""B2: BoardService - Rechte fuer Mensch und Agent, Verlauf, next_task (Plan board.md, Abschnitt 3)."""

import sqlite3
import threading

import pytest

from conclave.application.board import BoardError, BoardService
from conclave.domain.board import POSITION_STEP, StatusFlow
from conclave.domain.principal import AGENT_PRINCIPAL as AGENT
from conclave.domain.principal import HUMAN_PRINCIPAL as HUMAN
from conclave.infrastructure.sqlite.board_repository import SQLiteBoardRepository
from conclave.infrastructure.sqlite.connection import ThreadLocalConnection
from conclave.infrastructure.sqlite.schema import initialize_schema


@pytest.fixture
def board(crypto):
    conn = sqlite3.connect(":memory:")
    initialize_schema(conn)
    svc = BoardService(SQLiteBoardRepository(conn, crypto, autocommit=True))
    svc.create_project(HUMAN, "api", "API")
    return svc


def _forbidden(fn, *args, **kwargs):
    with pytest.raises(BoardError) as e:
        fn(*args, **kwargs)
    assert (e.value.status, e.value.type) == (403, "HumanOnly"), e.value
    return e.value


# ── Status ────────────────────────────────────────────────────────────────

def test_agent_cannot_move_to_or_from_the_last_column(board):
    board.create_task(AGENT, "api", "Ticket")
    board.update_task(AGENT, "api#1", status="review")                      # bis vor die letzte Spalte: ja
    _forbidden(board.update_task, AGENT, "api#1", status="done")
    board.update_task(HUMAN, "api#1", status="done")
    _forbidden(board.update_task, AGENT, "api#1", status="todo")             # aus done zurueck: nein
    assert board.get_task("api#1").status == "done"
    _forbidden(board.create_task, AGENT, "api", "gleich fertig", status="done")


def test_invalid_status_and_unknown_ticket(board):
    board.create_task(HUMAN, "api", "T")
    with pytest.raises(BoardError) as e:
        board.update_task(HUMAN, "api#1", status="fertig")
    assert e.value.status == 400
    with pytest.raises(BoardError) as e:
        board.get_task("api#9")
    assert e.value.status == 404
    with pytest.raises(BoardError) as e:
        board.get_task("api#12\n")
    assert e.value.status == 400


# ── Markierung "nur fuer Menschen" ────────────────────────────────────────

def test_agent_may_set_the_human_flag_but_not_remove_it(board):
    board.create_task(AGENT, "api", "Entscheidung: X?")
    assert board.update_task(AGENT, "api#1", human=True).human is True
    _forbidden(board.update_task, AGENT, "api#1", human=False)
    assert board.update_task(HUMAN, "api#1", human=False).human is False
    assert board.create_task(AGENT, "api", "gleich markiert", human=True).human is True


def test_human_only_tickets_are_read_only_for_agents(board):
    board.create_task(HUMAN, "api", "Privat", human=True)
    assert board.get_task("api#1").title == "Privat"                         # lesen: ja
    assert board.comments("api#1") == [] and board.history("api#1") == []
    _forbidden(board.update_task, AGENT, "api#1", title="geaendert")
    _forbidden(board.update_task, AGENT, "api#1", status="doing")
    _forbidden(board.add_comment, AGENT, "api#1", "darf ich?")
    board.add_comment(HUMAN, "api#1", "der Mensch darf")


# ── next_task ─────────────────────────────────────────────────────────────

def test_next_task_takes_the_top_ticket_skips_human_and_records_history(board):
    board.create_task(HUMAN, "api", "nur fuer Menschen", human=True)
    board.create_task(HUMAN, "api", "erstes fuer Agenten")
    board.create_task(HUMAN, "api", "zweites fuer Agenten")
    task = board.next_task(AGENT, "api")
    assert (task.ref, task.status) == ("api#2", "doing")
    [event] = board.history("api#2")
    assert (event.field_name, event.old_value, event.new_value, event.origin) == ("status", "todo", "doing", "agent")
    assert board.next_task(AGENT).ref == "api#3"
    assert board.next_task(AGENT) is None                                     # api#1 bleibt fuer Menschen
    assert board.get_task("api#1").status == "todo"


def test_parallel_next_task_never_hands_out_a_ticket_twice(tmp_path, crypto):
    conn = ThreadLocalConnection(tmp_path / "board.db")
    initialize_schema(conn)
    conn.commit()
    setup = BoardService(SQLiteBoardRepository(conn, crypto, autocommit=True))
    setup.create_project(HUMAN, "api", "API")
    for i in range(6):
        setup.create_task(HUMAN, "api", f"t{i}")
    setup.create_task(HUMAN, "api", "privat", human=True)
    barrier = threading.Barrier(8)
    got, errors = [], []

    def agent():
        svc = BoardService(SQLiteBoardRepository(conn, crypto, autocommit=True))
        barrier.wait()
        try:
            while (task := svc.next_task(AGENT, "api")) is not None:
                got.append(task.ref)
        except Exception as e:                                                # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=agent) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert sorted(got) == [f"api#{i}" for i in range(1, 7)]                   # jedes genau einmal
    assert "api#7" not in got


# ── Verlauf ───────────────────────────────────────────────────────────────

def test_history_shows_a_weakened_acceptance(board):
    board.create_task(HUMAN, "api", "T", description="## Abnahme\n- alle Tests gruen\n- Postgres geprueft")
    board.update_task(AGENT, "api#1", description="## Abnahme\n- Tests gruen")
    board.update_task(AGENT, "api#1", title="T2", status="doing")
    events = board.history("api#1")
    assert [(e.field_name, e.origin, e.actor_id) for e in events] == [
        ("description", "agent", "agent"), ("title", "agent", "agent"), ("status", "agent", "agent")]
    assert "Postgres geprueft" in events[0].old_value and "Postgres" not in events[0].new_value


def test_no_event_without_change(board):
    board.create_task(HUMAN, "api", "T")
    board.update_task(HUMAN, "api#1", title="T", tags=["x"])
    assert board.history("api#1") == []
    assert board.get_task("api#1").tags == ("x",)


# ── Kommentare ────────────────────────────────────────────────────────────

def test_comment_origins_and_immutability(board):
    board.create_task(HUMAN, "api", "T")
    mine = board.add_comment(HUMAN, "api#1", "von Laszlo", author_name="Laszlo")
    theirs = board.add_comment(AGENT, "api#1", "von cc", author_name="cc")
    system = board.add_system_comment("api#1", "Zweitmeinung", author_name="GPT · Conclave")
    assert [c.origin for c in board.comments("api#1")] == ["human", "agent", "system"]
    assert board.edit_comment(HUMAN, mine.id, "korrigiert").body == "korrigiert"
    _forbidden(board.edit_comment, HUMAN, theirs.id, "geaendert")             # Agenten-Kommentar: unveraenderlich
    _forbidden(board.edit_comment, HUMAN, system.id, "geaendert")
    _forbidden(board.edit_comment, AGENT, theirs.id, "geaendert")
    _forbidden(board.delete_comment, AGENT, mine.id)
    board.delete_comment(HUMAN, mine.id)
    assert [c.origin for c in board.comments("api#1")] == ["agent", "system"]


# ── Freigabe-Recht ────────────────────────────────────────────────────────

def test_approval_is_required_for_projects_and_deleting(board):
    board.create_task(AGENT, "api", "T")
    _forbidden(board.create_project, AGENT, "web", "Web")
    _forbidden(board.rename_project, AGENT, "api", "neu")
    _forbidden(board.delete_task, AGENT, "api#1")
    _forbidden(board.delete_project, AGENT, "api")
    board.delete_task(HUMAN, "api#1")
    with pytest.raises(BoardError) as e:
        board.create_project(HUMAN, "api", "doppelt")
    assert e.value.status == 409
    with pytest.raises(BoardError) as e:
        board.create_project(HUMAN, "Mit Leerzeichen", "x")
    assert e.value.status == 400


# ── Reihenfolge, Spalten aus der Konfiguration, Positionen ────────────────

def test_list_follows_the_configured_columns_and_hides_done(crypto):
    conn = sqlite3.connect(":memory:")
    initialize_schema(conn)
    svc = BoardService(SQLiteBoardRepository(conn, crypto, autocommit=True),
                       StatusFlow(("backlog", "in-arbeit", "pruefen", "fertig")))
    svc.create_project(HUMAN, "api", "API")
    for status in ("pruefen", "backlog", "fertig", "in-arbeit"):
        svc.create_task(HUMAN, "api", status, status=status)
    assert [t.status for t in svc.list_tasks("api")] == ["backlog", "in-arbeit", "pruefen"]
    assert [t.status for t in svc.list_tasks("api", include_done=True)][-1] == "fertig"
    assert svc.next_task(AGENT).status == "in-arbeit"


def test_move_with_index_and_renumbering_when_the_gap_is_exhausted(board):
    for i in range(3):
        board.create_task(HUMAN, "api", f"t{i}")
    board.update_task(HUMAN, "api#3", index=0)                                # ganz nach oben
    assert [t.ref for t in board.list_tasks("api")] == ["api#3", "api#1", "api#2"]
    # immer an Stelle 1 einfuegen, bis der Abstand erschoepft ist: die Spalte wird neu nummeriert
    for i in range(70):
        ref = board.create_task(HUMAN, "api", f"neu{i}").ref
        board.update_task(HUMAN, ref, index=1)
    refs = [t.ref for t in board.list_tasks("api")]
    assert refs[0] == "api#3" and refs[1] == "api#73" and refs[-2:] == ["api#1", "api#2"]
    positions = [t.position for t in board.list_tasks("api")]
    assert len(set(positions)) == len(positions)                              # keine Kollision
    assert max(positions) <= POSITION_STEP * (len(positions) + 2)              # nach Neunummerierung


def test_status_change_puts_the_card_at_the_end_of_the_new_column(board):
    board.create_task(HUMAN, "api", "a", status="doing")
    board.create_task(HUMAN, "api", "b")
    board.update_task(HUMAN, "api#2", status="doing")
    assert [t.ref for t in board.list_tasks("api", ["doing"])] == ["api#1", "api#2"]


# ── Suche ─────────────────────────────────────────────────────────────────

def test_search_covers_title_tags_description_and_comments(board):
    board.create_task(HUMAN, "api", "Login leer", tags=["frontend"])
    board.create_task(HUMAN, "api", "Export", description="CSV mit Umlauten")
    board.create_task(HUMAN, "api", "Sonstiges")
    board.add_comment(AGENT, "api#3", "Ursache liegt im Theme-Setting")
    board.create_task(HUMAN, "api", "erledigtes Login", status="done")
    assert [t.ref for t in board.search("login")] == ["api#1", "api#4"]
    assert [t.ref for t in board.search("FRONTEND")] == ["api#1"]
    assert [t.ref for t in board.search("umlauten")] == ["api#2"]
    assert [t.ref for t in board.search("theme-setting")] == ["api#3"]
    with pytest.raises(BoardError):
        board.search("  ")



def test_update_and_history_are_atomic(board, monkeypatch):
    """Faellt der Verlaufseintrag aus, bleibt auch die Aenderung am Ticket weg."""
    board.create_task(HUMAN, "api", "vorher")
    repo = board._repo
    real = repo._execute

    def broken(sql, params=()):
        if sql.startswith("INSERT INTO board_events"):
            raise sqlite3.OperationalError("simulierter Ausfall")
        return real(sql, params)

    monkeypatch.setattr(repo, "_execute", broken)
    with pytest.raises(sqlite3.OperationalError):
        board.update_task(AGENT, "api#1", title="nachher")
    monkeypatch.setattr(repo, "_execute", real)
    assert board.get_task("api#1").title == "vorher" and board.history("api#1") == []


def test_comments_keep_their_order_within_the_same_moment(board):
    board.create_task(HUMAN, "api", "T")
    for i in range(20):
        board.add_comment(AGENT, "api#1", f"k{i}")
    assert [c.body for c in board.comments("api#1")] == [f"k{i}" for i in range(20)]


# ── Review B2: Wettlaeufe zwischen Pruefen und Schreiben ──────────────────

def _stale(board, monkeypatch, ref):
    """Der Dienst liest kuenftig den jetzigen (dann veralteten) Stand des Tickets."""
    import copy
    old = copy.deepcopy(board.get_task(ref))
    monkeypatch.setattr(board, "get_task", lambda r: copy.deepcopy(old))


def test_agent_update_cannot_undo_a_flag_set_meanwhile(board, monkeypatch):
    board.create_task(HUMAN, "api", "T")
    _stale(board, monkeypatch, "api#1")
    BoardService.get_task(board, "api#1")
    board._repo.update_task(_set(board, "api#1", human=True))                 # der Mensch markiert inzwischen
    with pytest.raises(BoardError) as e:
        board.update_task(AGENT, "api#1", title="harmlos")
    assert (e.value.status, e.value.type) == (409, "Conflict")
    monkeypatch.undo()
    fresh = board.get_task("api#1")
    assert fresh.human is True and fresh.title == "T"
    assert [ev.field_name for ev in board.history("api#1")] == []             # kein Eintrag des Agenten


def test_agent_update_cannot_pull_a_ticket_back_from_done(board, monkeypatch):
    board.create_task(HUMAN, "api", "T", status="review")
    _stale(board, monkeypatch, "api#1")
    board._repo.update_task(_set(board, "api#1", status="done"))              # der Mensch schliesst inzwischen ab
    with pytest.raises(BoardError) as e:
        board.update_task(AGENT, "api#1", title="harmlos")
    assert e.value.status == 409
    monkeypatch.undo()
    assert board.get_task("api#1").status == "done"


def test_update_of_a_deleted_ticket_is_404(board, monkeypatch):
    board.create_task(HUMAN, "api", "T")
    _stale(board, monkeypatch, "api#1")
    task = BoardService.get_task(board, "api#1")
    board._repo.delete_task(task.id)
    with pytest.raises(BoardError) as e:
        board.update_task(HUMAN, "api#1", title="neu")
    assert e.value.status == 404


def test_next_task_does_not_hand_out_a_ticket_flagged_meanwhile(board, monkeypatch):
    board.create_task(HUMAN, "api", "T")
    stale = board.list_tasks("api", ["todo"])
    board._repo.update_task(_set(board, "api#1", human=True))                 # Markierung nach dem Lesen
    monkeypatch.setattr(board, "list_tasks", lambda *a, **k: stale)
    assert board.next_task(AGENT, "api") is None
    monkeypatch.undo()
    assert board.get_task("api#1").status == "todo" and board.history("api#1") == []


def test_version_grows_with_every_write(board):
    task = board.create_task(HUMAN, "api", "T")
    assert task.version == 1
    assert board.update_task(HUMAN, "api#1", title="T2").version == 2
    board.next_task(AGENT)
    assert board.get_task("api#1").version == 3


def _set(board, ref, **fields):
    task = BoardService.get_task(board, ref)
    for name, value in fields.items():
        setattr(task, name, value)
    return task



# ── Entscheidungen Laszlo (29.10.2026) ────────────────────────────────────

def test_history_keeps_a_long_description_in_full(board):
    """Eine abgeschwaechte Abnahme am Ende einer langen Beschreibung bleibt sichtbar."""
    head = "## Ziel\n" + "Ausfuehrliche Beschreibung. " * 40
    board.create_task(HUMAN, "api", "T", description=head + "\n## Abnahme\n- alle Tests gruen\n- Postgres geprueft")
    board.update_task(AGENT, "api#1", description=head + "\n## Abnahme\n- alle Tests gruen")
    [event] = board.history("api#1")
    assert event.old_value.endswith("- Postgres geprueft") and not event.new_value.endswith("geprueft")
    assert len(event.old_value) > 1000


def test_done_tickets_are_read_and_comment_only_for_agents(board):
    board.create_task(HUMAN, "api", "fertig", status="done")
    _forbidden(board.update_task, AGENT, "api#1", title="nachtraeglich")
    _forbidden(board.update_task, AGENT, "api#1", description="neu")
    _forbidden(board.update_task, AGENT, "api#1", index=0)
    assert board.add_comment(AGENT, "api#1", "Nachtrag: Doku verlinkt").origin == "agent"
    assert board.update_task(HUMAN, "api#1", title="vom Menschen").title == "vom Menschen"
