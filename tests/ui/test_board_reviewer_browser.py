"""W3 (#91): Das Board zeigt, ob der Reviewer laeuft; ist er aus und liegen Tickets in review, kommt
der Desktop-Hinweis genau einmal (je Ausfall), auch nach dem Neuladen nicht erneut.
"""

import pytest

from tests.ui.test_board_notify_browser import _enable, _notes, _open, _tick  # noqa: F401
from tests.ui.test_board_review_browser import _ticket_in_review, board_server  # noqa: F401


def _badge(page):
    badge = page.locator("#boardReviewer")
    badge.wait_for(state="visible", timeout=10000)
    return badge


@pytest.mark.parametrize("scheme", ["dark", "light"])
def test_badge_shows_active_or_off_with_text(chromium, board_server, scheme):
    context, page, errors = _open(chromium, board_server, scheme)
    try:
        badge = _badge(page)
        assert badge.get_attribute("data-state") == "off" and badge.inner_text().strip().endswith("Reviewer aus")
        board_server.reviewer.post("/board/v1/reviewer/heartbeat", json={"version": "test"})
        page.reload()
        page.click("[data-action='switch-tab'][data-tab='board']")
        badge = _badge(page)
        page.wait_for_function("() => document.getElementById('boardReviewer').dataset.state === 'active'",
                               timeout=10000)
        assert "Reviewer aktiv" in badge.inner_text()
        assert errors == []
    finally:
        context.close()


def test_off_reviewer_with_tickets_in_review_is_notified_once(chromium, board_server):
    _ticket_in_review(board_server, "Wartet")
    context, page, errors = _open(chromium, board_server)
    try:
        _enable(page)
        _tick(page)
        notes = _notes(page, reviewer_off=True)
        assert len(notes) == 1 and "1 Ticket" in notes[0]["body"]
        _tick(page)
        assert len(_notes(page, reviewer_off=True)) == 1      # nicht bei jedem Abruf
        page.reload()
        page.click("[data-action='switch-tab'][data-tab='board']")
        page.locator("#boardColumns .board-col").first.wait_for(timeout=10000)
        _tick(page)
        assert _notes(page, reviewer_off=True) == []          # auch nach dem Neuladen nicht
        assert errors == []
    finally:
        context.close()


def test_no_off_notice_without_tickets_in_review(chromium, board_server):
    context, page, _errors = _open(chromium, board_server)
    try:
        _enable(page)
        _tick(page)
        assert _notes(page, reviewer_off=True) == []
    finally:
        context.close()


def test_review_column_follows_the_server_rule(chromium, board_server):
    """#91-Review V1: "review", wenn vorhanden, sonst die vorletzte Spalte (wie StatusFlow.review)."""
    context, page, _errors = _open(chromium, board_server)
    try:
        cases = {"todo,doing,review,done": "review", "todo,review,test,done": "review",
                 "offen,arbeit,pruefung,fertig": "pruefung", "": "review"}
        for columns, expected in cases.items():
            got = page.evaluate("c => _reviewColumn(c ? c.split(',') : [])", columns)
            assert got == expected, columns
    finally:
        context.close()
