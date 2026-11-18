"""P8 (conclave#83): Desktop-Hinweis bei einem neuen Review-Ergebnis.

- ohne Einstellung gar nicht; die Erlaubnis fragt erst ein Klick an
- jedes Ergebnis genau einmal, auch nach dem Neuladen
- nur, wenn das Fenster nicht im Vordergrund ist
- der Text nennt das Urteil in Worten (nie nur Farbe), hell und dunkel gleich

Die Notification-API ersetzt ein Skript vor dem Laden durch einen Mitschreiber; der Fokus des
Fensters ist ueber ``window.__focus`` steuerbar, die Uhr ueber ``page.clock``.
"""

import pytest

from tests.ui.conftest import goto_board, reload_board  # noqa: F401
from tests.ui.test_board_review_browser import (  # noqa: F401
    HUMAN,
    _review,
    _ticket_in_review,
    board_server,
)

FAKE_NOTIFICATION = """
window.__notes = [];
window.__asked = 0;
window.__focus = false;
document.hasFocus = () => window.__focus;
class FakeNotification {
  constructor(title, options) { window.__notes.push({title, body: (options || {}).body || ''}); }
  close() {}
}
// Wie im Browser: die Erlaubnis bleibt ueber das Neuladen hinweg
FakeNotification.permission = localStorage.getItem('__permission') || 'default';
FakeNotification.requestPermission = async () => {
  window.__asked += 1;
  localStorage.setItem('__permission', 'granted');
  FakeNotification.permission = 'granted';
  return 'granted';
};
window.Notification = FakeNotification;
"""


def _open(chromium, server, scheme="dark"):
    context = chromium.new_context(color_scheme=scheme)
    context.add_init_script(FAKE_NOTIFICATION)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.clock.install()
    goto_board(page, server, HUMAN)
    page.locator("#boardColumns .board-col").first.wait_for(timeout=10000)
    return context, page, errors


def _tick(page):
    page.clock.run_for(16000)                       # ein Takt des Hinweis-Pollings (15 s)
    page.wait_for_timeout(300)


def _enable(page):
    page.locator("#boardNotify").click()
    page.locator("#boardNotify[aria-pressed='true']").wait_for(timeout=10000)


def _notes(page, *, reviewer_off: bool = False):
    """Hinweise zu Review-Ergebnissen; mit ``reviewer_off`` nur die zu einem ausgefallenen Reviewer (W3)."""
    notes = page.evaluate("window.__notes")
    return [n for n in notes if (n["title"] == "Reviewer aus") == reviewer_off]


@pytest.mark.parametrize("scheme", ["dark", "light"])
def test_result_is_notified_once_and_only_when_enabled(chromium, board_server, scheme):
    first = _ticket_in_review(board_server, "Erstes")
    context, page, errors = _open(chromium, board_server, scheme)
    try:
        button = page.locator("#boardNotify")
        assert button.is_visible() and button.get_attribute("aria-pressed") == "false"
        assert page.evaluate("window.__asked") == 0                       # nicht beim Seitenaufruf gefragt
        _review(board_server, first, "passed", blocking=0, suggestions=0)
        _tick(page)
        assert _notes(page) == []                                         # ohne Einstellung gar nicht

        _enable(page)
        assert page.evaluate("window.__asked") == 1
        _tick(page)
        assert _notes(page) == []                                         # alte Ergebnisse zaehlen nicht

        second = _ticket_in_review(board_server, "Zweites")
        _review(board_server, second, "rework", blocking=1, suggestions=2)
        _tick(page)
        notes = _notes(page)
        assert len(notes) == 1
        assert notes[0]["title"] == f"api#{second} Zweites"
        assert "gelb" in notes[0]["body"] and "1" in notes[0]["body"]
        _tick(page)
        assert len(_notes(page)) == 1                                     # genau einmal

        reload_board(page, board_server)
        page.locator("#boardColumns .board-col").first.wait_for(timeout=10000)
        _tick(page)
        assert _notes(page) == []                                         # auch nach dem Neuladen nicht erneut
        assert page.locator("#boardNotify").get_attribute("aria-pressed") == "true"
        assert errors == []
    finally:
        context.close()


def test_no_notification_while_the_window_is_in_front(chromium, board_server):
    number = _ticket_in_review(board_server, "Vorne")
    context, page, errors = _open(chromium, board_server)
    try:
        _enable(page)
        page.evaluate("window.__focus = true")
        _review(board_server, number, "failed", blocking=2, suggestions=0)
        _tick(page)
        assert _notes(page) == []
        page.evaluate("window.__focus = false")
        _tick(page)
        assert _notes(page) == []                                         # schon gesehen, nicht nachgeholt
        assert errors == []
    finally:
        context.close()


def test_green_says_it_waits_for_the_human(chromium, board_server):
    number = _ticket_in_review(board_server, "Fertig")
    context, page, _errors = _open(chromium, board_server)
    try:
        _enable(page)
        _review(board_server, number, "passed", blocking=0, suggestions=0)
        _tick(page)
        assert [n["body"] for n in _notes(page)] == ["grün – wartet auf dich"]
    finally:
        context.close()
