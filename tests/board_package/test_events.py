"""T9: Erweiterungspunkt Ereignisse im Kern (``BoardService.add_listener``), ohne Team-Code.

- jedes Schreiben meldet seine Ereignisse, ohne Inhalte (kein Titel, keine Texte)
- Herkunft und Konto stammen aus dem Zugang
- ein fehlerhafter Empfaenger laesst das Schreiben nie scheitern
- ohne Empfaenger aendert sich nichts (Personal)
"""

import logging

import pytest

from conclave_board.application.board import BoardService
from conclave_board.application.events import EVENT_TYPES, BoardEvent
from conclave_board.domain.principal import Principal
from conclave_board.infrastructure.migrations import run_board_migrations
from conclave_board.infrastructure.sqlite.board_repository import SQLiteBoardRepository
from conclave_board.infrastructure.sqlite.connection import ThreadLocalConnection

ANNA = Principal("human", actor_id="u_anna")
AGENT = Principal("agent", actor_id="u_anna")
REVIEWER = Principal("reviewer", actor_id="u_rev")


@pytest.fixture
def board(tmp_path):
    conn = ThreadLocalConnection(tmp_path / "board.db")
    run_board_migrations(conn)
    service = BoardService(SQLiteBoardRepository(conn, autocommit=True))
    service.create_project(ANNA, "api", "API")
    return service


@pytest.fixture
def seen(board):
    events: list[BoardEvent] = []
    board.add_listener(events.append)
    return events


def _types(events):
    return [e.type for e in events]


def test_create_move_comment_and_assign(board, seen):
    board.create_task(ANNA, "api", "Geheimer Titel", description="geheime Beschreibung")
    board.update_task(ANNA, "api#1", status="doing")
    comment = board.add_comment(AGENT, "api#1", "geheimer Kommentar")
    board.update_task(ANNA, "api#1", assignee="u_anna")
    assert _types(seen) == ["task.created", "task.status_changed", "task.commented", "task.assigned"]
    created, moved, commented, assigned = seen
    assert (created.ref, created.project, created.origin, created.actor_id) == ("api#1", "api", "human", "u_anna")
    assert created.data == {"status": "todo"}
    assert moved.data == {"old": "todo", "new": "doing"}
    assert (commented.origin, commented.data) == ("agent", {"comment_id": comment.id})
    assert assigned.data == {"old": None, "new": "u_anna"}
    text = repr(seen)
    assert "Geheim" not in text and "geheim" not in text                  # nie Inhalte


def test_next_task_reports_the_claim(board, seen):
    board.create_task(ANNA, "api", "T")
    seen.clear()
    board.next_task(AGENT, "api")
    assert _types(seen) == ["task.status_changed"] and seen[0].origin == "agent"


def test_claim_with_an_assignee_reports_both_in_order(board, seen):
    from conclave_board.application.policy import PersonalPolicy

    class Assigning(PersonalPolicy):
        def assignee_for(self, principal):
            return principal.actor_id

    board.policy = Assigning()
    board.create_task(ANNA, "api", "T")
    board.create_task(ANNA, "api", "U")
    seen.clear()
    board.next_task(AGENT, "api")
    board.next_task(AGENT, "api", task="api#2")
    assert _types(seen) == ["task.status_changed", "task.assigned"] * 2
    assert seen[1].data == {"old": None, "new": "u_anna"} and seen[3].ref == "api#2"


def test_review_result_carries_the_review_but_no_extra_comment(board, seen):
    board.create_task(ANNA, "api", "T", status="review")
    seen.clear()
    board.review(REVIEWER, "api#1", "running")
    assert seen == []                                                      # kein Ergebnis
    board.review(REVIEWER, "api#1", "rework", "Urteil: gelb", blocking=0, suggestions=2)
    assert _types(seen) == ["task.review_result", "task.status_changed"]
    result, back = seen
    assert result.data["state"] == "rework" and result.data["suggestions"] == 2 and result.data["comment_id"]
    assert result.origin == "reviewer" and back.data == {"old": "review", "new": "todo"}


def test_control_tickets_have_their_own_types(board, seen):
    board.create_task(ANNA, "api", "Pause", kind="control", control="hint", scope="project")
    board.add_comment(AGENT, "api#1", "gelesen")
    board.update_task(ANNA, "api#1", status="done")
    assert _types(seen) == ["control.created", "control.acknowledged", "control.status_changed"]
    assert seen[0].data == {"status": "todo", "control": "hint", "scope": "project"}


def test_a_failing_listener_never_fails_the_write(board, seen, caplog):
    def broken(event):
        raise RuntimeError("Empfaenger kaputt")

    board.add_listener(broken)
    with caplog.at_level(logging.ERROR, logger="conclave_board.events"):
        task = board.create_task(ANNA, "api", "T")
    assert task.ref == "api#1" and board.get_task("api#1")
    assert _types(seen) == ["task.created"]                                # andere Empfaenger bekommen es trotzdem
    assert "task.created an api#1 fehlgeschlagen" in caplog.text


def test_without_listeners_nothing_changes(board):
    board.create_task(ANNA, "api", "T")
    board.update_task(ANNA, "api#1", status="doing")
    assert board.get_task("api#1").status == "doing"


def test_every_reported_type_is_documented(board, seen):
    board.create_task(ANNA, "api", "T", status="review")
    board.add_comment(ANNA, "api#1", "x")
    board.update_task(ANNA, "api#1", assignee="u_anna")
    board.review(REVIEWER, "api#1", "passed", "gruen")
    assert set(_types(seen)) <= set(EVENT_TYPES)


# ── #77-Review V1: erst nach dem Commit, bei Rollback gar nicht ─────────

def _assigning(board):
    from conclave_board.application.policy import PersonalPolicy

    class Assigning(PersonalPolicy):
        def assignee_for(self, principal):
            return principal.actor_id

    board.policy = Assigning()


def test_no_event_when_the_claim_is_rolled_back(board, seen, monkeypatch):
    from conclave_board.application.board import BoardError
    _assigning(board)
    board.create_task(ANNA, "api", "T")
    seen.clear()
    original = board._repo.update_task

    def conflict(task, events=(), comment=None):
        if any(e.field_name == "assignee" for e in events):
            return False                                                 # Zustaendigkeit scheitert nach dem Claim
        return original(task, events, comment)

    monkeypatch.setattr(board._repo, "update_task", conflict)
    with pytest.raises(BoardError, match="inzwischen"):
        board.next_task(AGENT, "api", task="api#1")
    assert seen == []                                                    # kein Statuswechsel, den es nie gab


def test_events_are_published_after_the_lock_is_released(board, monkeypatch):
    from contextlib import contextmanager
    _assigning(board)
    board.create_task(ANNA, "api", "T")
    held = {"now": False}
    original = board._repo.locked_task

    @contextmanager
    def locked(task_id):
        with original(task_id):
            held["now"] = True
            try:
                yield
            finally:
                held["now"] = False

    monkeypatch.setattr(board._repo, "locked_task", locked)
    during = []
    board.add_listener(lambda event: during.append((event.type, held["now"])))
    board.next_task(AGENT, "api")
    assert during == [("task.status_changed", False), ("task.assigned", False)]


def test_a_rule_violation_under_the_status_lock_publishes_nothing(board, seen):
    from conclave_board.application.board import BoardError
    from conclave_board.application.policy import PersonalPolicy

    class Strict(PersonalPolicy):
        def lock_key(self, principal, task, new_status):
            return "k"

        def check_status_change(self, service, principal, task, new_status):
            raise BoardError("Regel verletzt", 409, "RuleViolation")

    board.create_task(ANNA, "api", "T")
    board.policy = Strict()
    seen.clear()
    with pytest.raises(BoardError, match="Regel"):
        board.update_task(ANNA, "api#1", status="doing")
    assert seen == []
