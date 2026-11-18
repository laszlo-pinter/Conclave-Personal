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


def _changes(board, ref):
    """Verlauf ohne das Anlegen (R9 schreibt dafuer immer einen Eintrag)."""
    return [e for e in board.history(ref) if e.field_name != "created"]


def _forbidden(fn, *args, **kwargs):
    with pytest.raises(BoardError) as e:
        fn(*args, **kwargs)
    assert (e.value.status, e.value.type) == (403, "HumanOnly"), e.value
    return e.value


# ── Status ────────────────────────────────────────────────────────────────

def test_agent_cannot_move_to_or_from_the_last_column(board):
    board.create_task(AGENT, "api", "Ticket")
    board.next_task(AGENT, task="api#1")                                    # erst uebernehmen (#51)
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
    assert board.comments("api#1") == [] and _changes(board, "api#1") == []
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
    [event] = _changes(board, "api#2")
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
    board.next_task(AGENT, task="api#1")                                    # uebernehmen statt PATCH (#51)
    board.update_task(AGENT, "api#1", title="T2")
    events = _changes(board, "api#1")
    assert [(e.field_name, e.origin, e.actor_id) for e in events] == [
        ("description", "agent", "agent"), ("status", "agent", "agent"), ("title", "agent", "agent")]
    assert "Postgres geprueft" in events[0].old_value and "Postgres" not in events[0].new_value


def test_no_event_without_change(board):
    board.create_task(HUMAN, "api", "T")
    board.update_task(HUMAN, "api#1", title="T", tags=["x"])
    assert [e.field_name for e in _changes(board, "api#1")] == ["tags"]     # Titel unveraendert: kein Eintrag
    assert board.get_task("api#1").tags == ("x",)
    board.update_task(HUMAN, "api#1", tags=["x"])
    assert [e.field_name for e in _changes(board, "api#1")] == ["tags"]


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
    assert board.get_task("api#1").title == "vorher" and _changes(board, "api#1") == []


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
    board._repo.update_task(_set(board, "api#1", human=True))                 # der Mensch markiert inzwischen
    with pytest.raises(BoardError) as e:
        board.update_task(AGENT, "api#1", title="harmlos")
    assert (e.value.status, e.value.type) == (409, "Conflict")
    monkeypatch.undo()
    fresh = board.get_task("api#1")
    assert fresh.human is True and fresh.title == "T"
    assert [ev.field_name for ev in _changes(board, "api#1")] == []             # kein Eintrag des Agenten


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
    assert board.get_task("api#1").status == "todo" and _changes(board, "api#1") == []


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
    [event] = _changes(board, "api#1")
    assert event.old_value.endswith("- Postgres geprueft") and not event.new_value.endswith("geprueft")
    assert len(event.old_value) > 1000


def test_done_tickets_are_read_and_comment_only_for_agents(board):
    board.create_task(HUMAN, "api", "fertig", status="done")
    _forbidden(board.update_task, AGENT, "api#1", title="nachtraeglich")
    _forbidden(board.update_task, AGENT, "api#1", description="neu")
    _forbidden(board.update_task, AGENT, "api#1", index=0)
    assert board.add_comment(AGENT, "api#1", "Nachtrag: Doku verlinkt").origin == "agent"
    assert board.update_task(HUMAN, "api#1", title="vom Menschen").title == "vom Menschen"



def test_agent_comment_respects_a_flag_set_meanwhile(board, monkeypatch):
    board.create_task(HUMAN, "api", "T")
    _stale(board, monkeypatch, "api#1")
    board._repo.update_task(_set(board, "api#1", human=True))
    token = board.change_token()
    _forbidden(board.add_comment, AGENT, "api#1", "kommt zu spaet")
    monkeypatch.undo()
    assert board.comments("api#1") == [] and board.change_token() == token     # nichts geschrieben
    assert board.add_comment(HUMAN, "api#1", "der Mensch darf").origin == "human"


# ── R4 (conclave#34): zwei Spalten, next_task schiebt nicht nach done ─────

def test_next_task_does_not_move_into_the_last_column_for_agents(crypto):
    conn = sqlite3.connect(":memory:")
    initialize_schema(conn)
    svc = BoardService(SQLiteBoardRepository(conn, crypto, autocommit=True), StatusFlow(("offen", "erledigt")))
    svc.create_project(HUMAN, "api", "API")
    svc.create_task(HUMAN, "api", "T")
    with pytest.raises(BoardError) as err:
        svc.next_task(AGENT, "api")
    assert err.value.status == 403
    assert svc.get_task("api#1").status == "offen"                          # nichts verschoben
    assert svc.next_task(HUMAN, "api").status == "erledigt"                 # Freigabe-Recht: erlaubt


# ── conclave#51: gezielt uebernehmen, doing nicht ueberspringen ───────────

def test_next_with_task_claims_exactly_that_ticket(board):
    board.create_task(HUMAN, "api", "eins")
    board.create_task(HUMAN, "api", "zwei")
    taken = board.next_task(AGENT, task="api#2")
    assert (taken.ref, taken.status) == ("api#2", "doing")
    assert board.get_task("api#1").status == "todo"
    [event] = _changes(board, "api#2")
    assert (event.old_value, event.new_value, event.origin) == ("todo", "doing", "agent")


@pytest.mark.parametrize("prepare, status", [
    (lambda b: b.update_task(HUMAN, "api#1", status="doing"), 409),        # schon uebernommen
    (lambda b: b.update_task(HUMAN, "api#1", human=True), 403),            # nur fuer Menschen
])
def test_next_with_task_refuses_and_changes_nothing(board, prepare, status):
    board.create_task(HUMAN, "api", "eins")
    prepare(board)
    before = board.get_task("api#1")
    with pytest.raises(BoardError) as err:
        board.next_task(AGENT, task="api#1")
    assert err.value.status == status
    after = board.get_task("api#1")
    assert (after.status, after.version) == (before.status, before.version)


def test_next_with_unknown_task_is_404(board):
    with pytest.raises(BoardError) as err:
        board.next_task(AGENT, task="api#99")
    assert err.value.status == 404


def test_parallel_targeted_claims_have_one_winner(crypto, tmp_path):
    conn = ThreadLocalConnection(tmp_path / "b.db")
    initialize_schema(conn)
    svc = BoardService(SQLiteBoardRepository(conn, crypto, autocommit=True), StatusFlow())
    svc.create_project(HUMAN, "api", "API")
    svc.create_task(HUMAN, "api", "eins")
    results = []

    def take():
        try:
            results.append(svc.next_task(AGENT, task="api#1").ref)
        except BoardError as e:
            results.append(e.status)

    threads = [threading.Thread(target=take) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("api#1") == 1 and set(results) - {"api#1"} <= {409}


def test_agent_cannot_skip_doing(board):
    board.create_task(HUMAN, "api", "eins")
    with pytest.raises(BoardError) as err:
        board.update_task(AGENT, "api#1", status="review")
    assert err.value.status == 403 and "uebernehmen" in str(err.value)
    with pytest.raises(BoardError):
        board.update_task(AGENT, "api#1", status="doing")                     # nur ueber next(task=...)
    board.next_task(AGENT, task="api#1")
    assert board.update_task(AGENT, "api#1", status="review").status == "review"
    assert board.update_task(AGENT, "api#1", status="doing").status == "doing"   # Rueckweg erlaubt
    board.update_task(HUMAN, "api#1", status="todo")
    assert board.update_task(HUMAN, "api#1", status="review").status == "review"  # der Mensch darf alles


# ── P1 (conclave#56): Prioritaet nur durch Plan oder Mensch ───────────────

def _todo(board):
    return [t.ref for t in board.list_tasks("api", ["todo"])]


def test_new_tickets_keep_plan_order_by_rank(board):
    for title in ("eins", "zwei", "drei"):
        board.create_task(HUMAN, "api", title)
    ranks = [board.get_task(f"api#{n}").rank for n in (1, 2, 3)]
    assert ranks == sorted(ranks) and len(set(ranks)) == 3
    assert _todo(board) == ["api#1", "api#2", "api#3"]


@pytest.mark.parametrize("field", [{"index": 0}, {"rank": 1.0}])
def test_agent_cannot_change_priority(board, field):
    board.create_task(HUMAN, "api", "eins")
    board.create_task(HUMAN, "api", "zwei")
    before = _changes(board, "api#2")
    with pytest.raises(BoardError) as err:
        board.update_task(AGENT, "api#2", **field)
    assert err.value.status == 403 and err.value.type == "HumanOnly"
    assert _changes(board, "api#2") == before and _todo(board) == ["api#1", "api#2"]


def test_ticket_back_in_todo_returns_to_its_rank(board):
    for title in ("eins", "zwei", "drei"):
        board.create_task(HUMAN, "api", title)
    board.next_task(AGENT, task="api#1")
    board.update_task(AGENT, "api#1", status="review")
    board.update_task(AGENT, "api#1", status="todo")                       # zurueck (z. B. Nacharbeit)
    assert _todo(board) == ["api#1", "api#2", "api#3"]                      # nicht ans Ende


def test_human_reorders_and_next_task_follows(board):
    for title in ("eins", "zwei", "drei"):
        board.create_task(HUMAN, "api", title)
    board.update_task(HUMAN, "api#3", index=0)                              # Drag & Drop nach oben
    assert _todo(board) == ["api#3", "api#1", "api#2"]
    [event] = [e for e in _changes(board, "api#3") if e.field_name == "rank"]
    assert event.origin == "human"
    assert board.next_task(AGENT, "api").ref == "api#3"
    board.update_task(HUMAN, "api#2", rank=-5.0)                            # Feld "Prioritaet"
    assert board.next_task(AGENT, "api").ref == "api#2"


def test_moving_forward_is_work_state_not_priority(board):
    for title in ("eins", "zwei"):
        board.create_task(HUMAN, "api", title)
    board.next_task(AGENT, task="api#2")
    board.next_task(AGENT, task="api#1")
    doing = [t.ref for t in board.list_tasks("api", ["doing"])]
    assert doing == ["api#2", "api#1"]                                      # Reihenfolge des Ankommens


def test_renumbering_in_another_column_does_not_block_the_human(board):
    """P1-Review: Neunummerieren erhoeht die Version; der Mensch, der es ausloest, schreibt trotzdem."""
    for i in range(3):
        board.create_task(HUMAN, "api", f"t{i}", status="doing")
    for i in range(70):
        ref = board.create_task(HUMAN, "api", f"neu{i}", status="doing").ref
        board.update_task(HUMAN, ref, index=1)
    refs = [t.ref for t in board.list_tasks("api", ["doing"])]
    assert refs[1] == "api#73" and len(set(t.position for t in board.list_tasks("api", ["doing"]))) == 73


def _store(board, ref, **fields):
    """Felder direkt im Repository setzen (ohne Dienst), z. B. enge Raenge fuer das Neunummerieren."""
    task = board.get_task(ref)
    for name, value in fields.items():
        setattr(task, name, value)
    assert board._repo.update_task(task)


def test_agent_update_racing_a_rank_renumber_cannot_restore_the_old_rank(board, monkeypatch):
    """P1-Review, Korrektur 1: Rennen zwischen Lesen des Agenten und Neunummerieren -> 409, Rang bleibt."""
    board.create_task(HUMAN, "api", "a")
    board.create_task(HUMAN, "api", "b")
    _store(board, "api#1", rank=5.0)                                  # ungleichmaessig: Neunummerieren aendert ihn
    _store(board, "api#2", rank=7.0)
    real_get = board._repo.get_task
    after = {}

    def get_then_renumber(slug, number):
        task = real_get(slug, number)
        board._repo.renumber_ranks(task.project_id)               # der Mensch nummeriert dazwischen neu
        after["rank"] = real_get(slug, number).rank
        return task

    monkeypatch.setattr(board._repo, "get_task", get_then_renumber)
    with pytest.raises(BoardError) as e:
        board.update_task(AGENT, "api#1", description="nur Text")
    monkeypatch.undo()
    assert e.value.status == 409
    assert after["rank"] != 5.0                                     # der Rang hat sich wirklich geaendert
    task = board.get_task("api#1")
    assert task.rank == after["rank"] and task.description == ""


@pytest.mark.parametrize("column", ["todo", "doing"])
def test_human_move_with_renumber_does_not_overwrite_a_foreign_change(board, monkeypatch, column):
    """P1-Folgereview V1: Aendert jemand das Ticket zwischen Lesen und Neunummerieren, gibt es 409."""
    for title in ("a", "b", "c"):
        board.create_task(HUMAN, "api", title, status=column)
    field = "rank" if column == "todo" else "position"
    _store(board, "api#1", **{field: 1.0})
    _store(board, "api#2", **{field: 1.0 + 1e-9})                     # kein Platz dazwischen
    _store(board, "api#3", **{field: 5.0})
    name = "renumber_ranks" if column == "todo" else "renumber_column"
    real = getattr(board._repo, name)

    def foreign_change_then_renumber(*args):
        _store(board, "api#3", description="vom Agenten")             # fremde Aenderung dazwischen
        return real(*args)

    monkeypatch.setattr(board._repo, name, foreign_change_then_renumber)
    with pytest.raises(BoardError) as e:
        board.update_task(HUMAN, "api#3", title="vom Menschen", index=1)
    monkeypatch.undo()
    assert (e.value.status, e.value.type) == (409, "Conflict")
    task = board.get_task("api#3")
    assert (task.description, task.title) == ("vom Agenten", "c")


def test_delete_project_only_empty(board):
    """U4: mit only_empty 409 ProjectNotEmpty, solange es Tickets gibt; ohne den Schalter wie bisher samt Tickets."""
    board.create_task(AGENT, "api", "Ticket")
    with pytest.raises(BoardError) as e:
        board.delete_project(HUMAN, "api", only_empty=True)
    assert (e.value.status, e.value.type) == (409, "ProjectNotEmpty")
    assert [t.ref for t in board.list_tasks("api", include_done=True)] == ["api#1"]
    _forbidden(board.delete_project, AGENT, "api", only_empty=True)
    board.create_project(HUMAN, "leer", "Leer")
    board.delete_project(HUMAN, "leer", only_empty=True)
    with pytest.raises(BoardError) as e:
        board.delete_project(HUMAN, "leer", only_empty=True)
    assert e.value.status == 404
    board.delete_project(HUMAN, "api")
    assert board.list_projects() == []
