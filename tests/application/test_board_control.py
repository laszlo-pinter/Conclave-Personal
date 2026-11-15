"""P6 (conclave#61): Steuertickets - Pause und Hinweis vom Menschen an die Agenten.

- Steuertickets (kind=control) legt nur der Mensch an, aendert und schliesst sie.
- Offene Pause: next liefert kein Ticket, sondern die Pause; Geltung Projekt oder alle.
- Hinweis: bleibt im Feld control, bis ein Agent ihn per Kommentar quittiert.
- Ein normales Ticket mit "Pause"-Text loest nichts aus.
"""

import sqlite3

import pytest

from conclave.application.board import BoardError, BoardService, task_to_dict
from conclave.domain.principal import AGENT_PRINCIPAL as AGENT
from conclave.domain.principal import HUMAN_PRINCIPAL as HUMAN
from conclave.domain.principal import REVIEWER_PRINCIPAL as REVIEWER
from conclave.infrastructure.sqlite.board_repository import SQLiteBoardRepository
from conclave.infrastructure.sqlite.schema import initialize_schema


@pytest.fixture
def board(crypto):
    conn = sqlite3.connect(":memory:")
    initialize_schema(conn)
    svc = BoardService(SQLiteBoardRepository(conn, crypto, autocommit=True))
    svc.create_project(HUMAN, "api", "API")
    svc.create_project(HUMAN, "web", "Web")
    svc.create_task(HUMAN, "api", "Arbeit A")                           # api#1
    svc.create_task(HUMAN, "web", "Arbeit W")                           # web#1
    return svc


def _pause(board, slug="api", scope="all", reason="Bitte anhalten"):
    return board.create_task(HUMAN, slug, reason, kind="control", control="pause", scope=scope)


def _forbidden(fn, *args, **kwargs):
    with pytest.raises(BoardError) as e:
        fn(*args, **kwargs)
    assert e.value.status == 403, e.value
    return e.value


# ── Wer darf ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("who", [AGENT, REVIEWER])
def test_only_the_human_creates_control_tickets(board, who):
    _forbidden(board.create_task, who, "api", "Pause", kind="control", control="pause")
    assert board.control_state()["pauses"] == []


def test_agent_cannot_change_or_close_a_control_ticket(board):
    pause = _pause(board)
    _forbidden(board.update_task, AGENT, pause.ref, title="weiter")
    _forbidden(board.update_task, AGENT, pause.ref, status="done")
    _forbidden(board.next_task, AGENT, task=pause.ref)
    assert board.get_task(pause.ref).status == "todo"


def test_control_needs_a_known_type_and_scope(board):
    for kwargs in ({"control": "stopp"}, {"control": None}, {"control": "pause", "scope": "welt"}):
        with pytest.raises(BoardError) as e:
            board.create_task(HUMAN, "api", "x", kind="control", **kwargs)
        assert e.value.status == 400
    with pytest.raises(BoardError):
        board.create_task(HUMAN, "api", "x", kind="unbekannt")


# ── Pause ───────────────────────────────────────────────────────────────────

def _paused(board, **kwargs):
    with pytest.raises(BoardError) as e:
        board.next_task(AGENT, **kwargs)
    assert (e.value.status, e.value.type) == (409, "Paused")
    return e.value.pause


def test_open_pause_stops_next_and_closing_releases_it(board):
    pause = _pause(board, reason="Erst Tests von R7")
    info = _paused(board)
    assert (info["task"], info["reason"], info["by"]) == (pause.ref, "Erst Tests von R7", "human")
    assert board.get_task("api#1").status == "todo"                  # nichts uebernommen
    _paused(board, task="api#1")                                      # auch gezielt nicht
    board.update_task(HUMAN, pause.ref, status="done")               # Mensch schliesst
    assert board.next_task(AGENT).ref == "api#1"


def test_project_pause_only_stops_that_project(board):
    _pause(board, slug="api", scope="project")
    _paused(board, slug="api")
    _paused(board)                                                    # ohne Projekt: vorsichtshalber auch
    assert board.next_task(AGENT, slug="web").ref == "web#1"


def test_pause_tickets_are_never_handed_out(board):
    pause = _pause(board)
    board.update_task(HUMAN, pause.ref, status="done")
    board.create_task(HUMAN, "api", "Hinweis", kind="control", control="hint")
    refs = []
    while (t := board.next_task(AGENT)) is not None:
        refs.append(t.ref)
    assert refs == ["api#1", "web#1"]


def test_ordinary_ticket_with_pause_text_does_nothing(board):
    board.create_task(AGENT, "api", "Pause, alle Agenten anhalten", description="kind=control pause")
    board.create_task(HUMAN, "api", "Pause, alle Agenten anhalten")
    state = board.control_state()
    assert state == {"pauses": [], "hints": []}
    assert board.next_task(AGENT) is not None


# ── Hinweis ─────────────────────────────────────────────────────────────────

def test_hint_stays_until_an_agent_acknowledges_it(board):
    hint = board.create_task(HUMAN, "api", "Ab jetzt zuerst die Tests", kind="control", control="hint")
    assert [h["task"] for h in board.control_state()["hints"]] == [hint.ref]
    board.add_comment(HUMAN, hint.ref, "Rueckfrage vom Menschen")      # zaehlt nicht als Quittung
    assert board.control_state()["hints"]
    board.add_comment(AGENT, hint.ref, "Verstanden, mache ich", author_name="cc")
    assert board.control_state()["hints"] == []
    task = board.get_task(hint.ref)
    assert (task.control_ack_by, task.status) == ("cc (agent)", "todo")   # schliesst weiter der Mensch
    assert task_to_dict(task)["directive"]["ack_by"] == "cc (agent)"
    assert ("control_ack", "cc (agent)", "agent") in [(e.field_name, e.new_value, e.origin) for e in board.history(hint.ref)]


def test_hint_does_not_stop_next(board):
    board.create_task(HUMAN, "api", "Hinweis", kind="control", control="hint")
    assert board.next_task(AGENT).ref == "api#1"


def test_control_state_lists_open_pauses_with_scope(board):
    p1 = _pause(board, slug="api", scope="project")
    p2 = _pause(board, slug="web", scope="all", reason="Alle anhalten")
    state = board.control_state()
    assert [(p["task"], p["scope"]) for p in state["pauses"]] == [(p1.ref, "api"), (p2.ref, "all")]
    assert [p["task"] for p in board.control_state(slug="web")["pauses"]] == [p2.ref]


# ── Nacharbeit aus dem Review (V1, V2) ──────────────────────────────────────

def test_acknowledgement_names_the_role_not_only_a_claimed_name(board):
    hint = board.create_task(HUMAN, "api", "Hinweis", kind="control", control="hint")
    board.add_comment(AGENT, hint.ref, "ok", author_name="Laszlo")
    assert board.get_task(hint.ref).control_ack_by == "Laszlo (agent)"


def test_acknowledgement_without_a_name_uses_the_role(board):
    hint = board.create_task(HUMAN, "api", "Hinweis", kind="control", control="hint")
    board.add_comment(AGENT, hint.ref, "ok")
    assert board.get_task(hint.ref).control_ack_by == "agent"


def test_control_state_reads_only_control_tickets(board, monkeypatch):
    seen = []
    real = board._repo.list_tasks

    def spy(slug=None, statuses=None, kind=None):
        seen.append(kind)
        return real(slug, statuses, kind=kind)

    monkeypatch.setattr(board._repo, "list_tasks", spy)
    _pause(board)
    seen.clear()
    board.control_state()
    assert seen == ["control"]
    assert {t.kind for t in real(None, None, kind="control")} == {"control"}
