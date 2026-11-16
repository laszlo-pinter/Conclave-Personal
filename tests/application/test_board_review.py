"""P3 (conclave#58): Reviewer-Zugang, Review-Status und Nacharbeit-Schleife.

- Nur der Reviewer setzt den Review-Status; Ergebnis und Kommentar gehen zusammen.
- rework/failed schieben das Ticket nach ``todo``; ``next_task`` liefert Nacharbeit zuerst.
- passed bleibt in ``review``; nach ``done`` schiebt weiter nur der Mensch.
- Drei rote Reviews in Folge machen das Ticket "nur fuer Menschen" (E-R3).
- Der Reviewer darf lesen und kommentieren, sonst nichts.
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
    return svc


def _in_review(board, title="T"):
    task = board.create_task(HUMAN, "api", title)
    board.update_task(HUMAN, task.ref, status="review")
    return task.ref


def _error(fn, *args, **kwargs):
    with pytest.raises(BoardError) as e:
        fn(*args, **kwargs)
    return e.value


# ── Wer darf ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("principal", [AGENT, HUMAN])
def test_only_the_reviewer_sets_the_review_state(board, principal):
    ref = _in_review(board)
    err = _error(board.review, principal, ref, "passed", "Urteil: gruen")
    assert err.status == 403
    assert board.get_task(ref).review_state == "none"
    assert board.comments(ref) == []


def test_reviewer_cannot_create_move_rank_or_claim(board):
    ref = _in_review(board)
    assert _error(board.create_task, REVIEWER, "api", "Neu").status == 403
    assert _error(board.update_task, REVIEWER, ref, status="done").status == 403
    assert _error(board.update_task, REVIEWER, ref, title="anders").status == 403
    assert _error(board.update_task, REVIEWER, ref, rank=1.0).status == 403
    board.create_task(HUMAN, "api", "Frei")
    assert _error(board.next_task, REVIEWER).status == 403
    assert board.get_task(ref).status == "review"


def test_reviewer_comments_carry_the_reviewer_origin(board):
    ref = _in_review(board)
    comment = board.add_comment(REVIEWER, ref, "Zwischenstand")
    assert comment.origin == "reviewer"


# ── Ergebnisse ──────────────────────────────────────────────────────────────

def test_running_then_passed_stays_in_review(board):
    ref = _in_review(board)
    board.review(REVIEWER, ref, "running")
    assert board.get_task(ref).review_state == "running"
    task = board.review(REVIEWER, ref, "passed", "Urteil: gruen", blocking=0, suggestions=0,
                        checked="sicherheit @ abc..def")
    assert (task.status, task.review_state) == ("review", "passed")
    assert (task.review_blocking, task.review_suggestions, task.review_checked) == (0, 0, "sicherheit @ abc..def")
    assert task.review_at is not None
    [comment] = board.comments(ref)
    assert (comment.origin, comment.body) == ("reviewer", "Urteil: gruen")


def test_rework_moves_to_the_top_of_todo_and_next_delivers_it_with_the_review(board):
    board.create_task(HUMAN, "api", "Plan zuerst")                       # api#1, Rang vorn
    ref = _in_review(board, "Nacharbeit")                                 # api#2
    task = board.review(REVIEWER, ref, "rework", "Urteil: gelb\nB1 x", blocking=1, suggestions=2)
    assert (task.status, task.review_state) == ("todo", "rework")
    assert [t.ref for t in board.list_tasks("api", ["todo"])] == [ref, "api#1"]
    taken = board.next_task(AGENT)
    assert taken.ref == ref
    assert board.last_review(ref).body == "Urteil: gelb\nB1 x"
    history = [(e.field_name, e.new_value, e.origin) for e in board.history(ref)]
    assert ("review_state", "rework", "reviewer") in history
    assert ("status", "todo", "system") in history


def test_review_only_in_the_review_column(board):
    task = board.create_task(HUMAN, "api", "T")
    err = _error(board.review, REVIEWER, task.ref, "passed", "gruen")
    assert (err.status, err.type) == (409, "NotInReview")


def test_result_needs_a_comment_and_a_known_state(board):
    ref = _in_review(board)
    assert _error(board.review, REVIEWER, ref, "passed", "").status == 400
    assert _error(board.review, REVIEWER, ref, "gruen", "x").status == 400
    assert _error(board.review, REVIEWER, ref, "none", "x").status == 400
    assert _error(board.review, REVIEWER, ref, "rework", "x", blocking=-1).status == 400
    assert _error(board.review, REVIEWER, ref, "rework", "x", blocking=True).status == 400


def test_moving_back_to_review_resets_the_state(board):
    ref = _in_review(board)
    board.review(REVIEWER, ref, "rework", "gelb")
    board.next_task(AGENT, task=ref)
    board.update_task(AGENT, ref, status="review")
    task = board.get_task(ref)
    assert (task.status, task.review_state) == ("review", "none")


# ── Drei rote in Folge (E-R3) ───────────────────────────────────────────────

def _round(board, ref, state):
    board.review(REVIEWER, ref, state, f"Urteil: {state}")
    if board.get_task(ref).status == "todo" and not board.get_task(ref).human:
        board.next_task(AGENT, task=ref)
        board.update_task(AGENT, ref, status="review")


def test_third_red_review_in_a_row_hands_the_ticket_to_the_human(board):
    ref = _in_review(board)
    _round(board, ref, "failed")
    _round(board, ref, "failed")
    assert board.get_task(ref).review_red_count == 2
    board.review(REVIEWER, ref, "failed", "Urteil: rot")
    task = board.get_task(ref)
    assert (task.status, task.human, task.review_red_count) == ("todo", True, 3)
    assert board.next_task(AGENT) is None
    assert ("human", "True", "system") in [(e.field_name, e.new_value, e.origin) for e in board.history(ref)]


def test_yellow_does_not_count_and_green_resets(board):
    ref = _in_review(board)
    _round(board, ref, "failed")
    _round(board, ref, "rework")
    assert board.get_task(ref).review_red_count == 1
    _round(board, ref, "failed")
    assert board.get_task(ref).review_red_count == 2
    board.review(REVIEWER, ref, "passed", "gruen")
    assert board.get_task(ref).review_red_count == 0


def test_task_dict_carries_the_review_fields(board):
    ref = _in_review(board)
    board.review(REVIEWER, ref, "rework", "gelb", blocking=0, suggestions=3, checked="b @ 1..2")
    data = task_to_dict(board.get_task(ref))
    assert data["review"] == {"state": "rework", "at": data["review"]["at"], "red_count": 0,
                              "blocking": 0, "suggestions": 3, "checked": "b @ 1..2"}


# ── Nacharbeit aus dem Review (Freigabe Laszlo, Chat #79) ───────────────────

def test_rework_comes_first_across_projects(board):
    """V1: next ohne Projekt liefert Nacharbeit aus jedem Projekt vor normalen Tickets anderer Projekte."""
    board.create_project(HUMAN, "zzz", "Spaeteres Projekt")
    board.create_task(HUMAN, "api", "Normal im ersten Projekt")              # api#1
    task = board.create_task(HUMAN, "zzz", "Nacharbeit im spaeteren Projekt")
    board.update_task(HUMAN, task.ref, status="review")
    board.review(REVIEWER, task.ref, "rework", "gelb")
    assert board.next_task(AGENT).ref == task.ref
    assert board.next_task(AGENT).ref == "api#1"                           # danach Rang wie bisher


def test_red_counter_resets_when_the_human_releases_the_ticket(board):
    """V2: Nimmt der Mensch "nur fuer Menschen" nach drei roten weg, beginnt die Zaehlung neu."""
    ref = _in_review(board)
    for _ in range(3):
        _round(board, ref, "failed")
    assert (board.get_task(ref).human, board.get_task(ref).review_red_count) == (True, 3)
    board.update_task(HUMAN, ref, human=False)
    assert board.get_task(ref).review_red_count == 0
    history = [(e.field_name, e.old_value, e.new_value, e.origin) for e in board.history(ref)]
    assert ("review_red_count", "3", "0", "human") in history
    board.next_task(AGENT, task=ref)
    board.update_task(AGENT, ref, status="review")
    board.review(REVIEWER, ref, "failed", "rot")
    assert (board.get_task(ref).human, board.get_task(ref).review_red_count) == (False, 1)


def test_setting_human_again_keeps_the_counter(board):
    ref = _in_review(board)
    _round(board, ref, "failed")
    board.update_task(HUMAN, ref, human=True)
    assert board.get_task(ref).review_red_count == 1
