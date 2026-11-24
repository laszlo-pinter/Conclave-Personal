"""P4 (conclave#59): Review-Status an der Karte, Hinweis auf Freigaben, Drag & Drop nur fuer den Menschen.

Ohne das Ticket zu oeffnen soll sichtbar sein: Review laeuft, gruen, gelb, rot und haengt.
Farbe nie allein: Text und Symbol neben der Farbe, ``aria-label``; Kontrast mindestens 4,5:1.

Die UI hat nur ein dunkles Theme (kein ``prefers-color-scheme``). Der Lauf mit hell
eingestelltem Browser prueft also kein helles Design, sondern nur, dass die Anzeige dann
dieselben Farben behaelt und lesbar bleibt.
"""

import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from tests.ui.conftest import goto_board, reload_board  # noqa: F401

HUMAN = "cvh_p4-mensch"
AGENT = "cva_p4-agent"
REVIEWER = "cvr_p4-reviewer"


@pytest.fixture
def board_server(tmp_path, monkeypatch, board_surface):
    from werkzeug.serving import make_server

    from conclave.api.server import _build_app
    from conclave.cli.config import ConclaveConfig

    (tmp_path / "workspace").mkdir()
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("CONCLAVE_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.delenv("CONCLAVE_API_KEY", raising=False)
    app, _ = _build_app(ConclaveConfig(db_path=tmp_path / "conclave.db", api_key=HUMAN, agent_api_key=AGENT,
                                       reviewer_api_key=REVIEWER, mode="development"))
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    api = SimpleNamespace(
        surface=board_surface, url=url, db=tmp_path / "conclave.db",
        human=httpx.Client(base_url=url, headers={"Authorization": f"Bearer {HUMAN}"}),
        agent=httpx.Client(base_url=url, headers={"Authorization": f"Bearer {AGENT}"}),
        reviewer=httpx.Client(base_url=url, headers={"Authorization": f"Bearer {REVIEWER}"}))
    assert api.human.post("/board/projects", json={"slug": "api", "name": "API"}).status_code == 201
    try:
        yield api
    finally:
        for client in (api.human, api.agent, api.reviewer):
            client.close()
        server.shutdown()
        thread.join(timeout=5)


REVIEW_TEXT = "Urteil: gelb\nBlockierend:\n- keine\nVorschlaege:\n- V1 x"


def _ticket_in_review(server, title):
    """Ticket anlegen und bis nach review bringen; gibt die Nummer zurueck."""
    number = server.agent.post("/board/tasks", json={"project": "api", "title": title}).json()["number"]
    server.agent.post("/board/next", json={"task": f"api#{number}"})
    server.agent.patch(f"/board/projects/api/tasks/{number}", json={"status": "review"})
    return number


def _review(server, number, state, **extra):
    body = {"state": state, "comment": "" if state == "running" else REVIEW_TEXT, **extra}
    resp = server.reviewer.post(f"/board/projects/api/tasks/{number}/review", json=body)
    assert resp.status_code == 200, resp.text


def _states(server):
    """Ein Ticket je Zustand: running, passed, rework (zurueck in todo), failed, haengt."""
    n = {name: _ticket_in_review(server, name) for name in ("laeuft", "gruen", "gelb", "rot", "haengt")}
    _review(server, n["laeuft"], "running")
    _review(server, n["gruen"], "running")
    _review(server, n["gruen"], "passed", blocking=0, suggestions=0)
    _review(server, n["gelb"], "running")
    _review(server, n["gelb"], "rework", blocking=0, suggestions=3)
    _review(server, n["rot"], "running")
    _review(server, n["rot"], "failed", blocking=2, suggestions=1)
    _review(server, n["haengt"], "running")
    # "haengt": Review vor 45 Minuten gestartet (direkt in der Test-DB zurueckdatiert)
    import sqlite3
    conn = sqlite3.connect(server.db)
    conn.execute("UPDATE board_tasks SET review_at = ? WHERE number = ?",
                 ((datetime.now(UTC) - timedelta(minutes=45)).isoformat(), n["haengt"]))
    conn.commit()
    conn.close()
    return n


def _open_board(browser, server, scheme="dark", token=HUMAN):
    context = browser.new_context(color_scheme=scheme)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    goto_board(page, server, token)
    page.locator("#boardColumns .board-col").first.wait_for(timeout=10000)
    return context, page, errors


def _card(page, number):
    return page.locator(f"#boardColumns .board-card[data-ref='api#{number}']")


def _luminance(rgb: str) -> float:
    parts = [int(float(x)) for x in rgb[rgb.index("(") + 1:rgb.index(")")].split(",")[:3]]

    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in parts)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(page, element):
    color = element.evaluate("e => getComputedStyle(e).color")
    bg = element.evaluate("""e => { let n = e; while (n) { const c = getComputedStyle(n).backgroundColor;
        if (c && c !== 'rgba(0, 0, 0, 0)' && c !== 'transparent') return c; n = n.parentElement; }
        return getComputedStyle(document.body).backgroundColor; }""")
    l1, l2 = sorted((_luminance(color), _luminance(bg)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


EXPECTED = {
    "laeuft": ("running", "Review läuft"),
    "gruen": ("passed", "in Ordnung"),
    "gelb": ("rework", "Nacharbeit"),
    "rot": ("failed", "nicht bestanden"),
    "haengt": ("stuck", "Review hängt"),
}


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_every_review_state_is_visible_on_the_card_with_text(chromium, board_server, scheme):
    numbers = _states(board_server)
    context, page, errors = _open_board(chromium, board_server, scheme)
    try:
        for name, (state, text) in EXPECTED.items():
            badge = _card(page, numbers[name]).locator(".board-review")
            badge.wait_for(timeout=10000)
            assert badge.get_attribute("data-state") == state, name
            assert text in badge.inner_text(), (name, badge.inner_text())               # Text neben der Farbe
            assert text in (badge.get_attribute("aria-label") or ""), name
            assert badge.locator(".board-review-symbol").inner_text().strip(), name       # und ein Symbol
            assert _contrast(page, badge) >= 4.5, (scheme, name)
        # gelb kehrt nach todo zurueck und behaelt das Badge mit Datum; rot zeigt die Runden
        assert _card(page, numbers["gelb"]).evaluate("c => c.closest('.board-col').dataset.status") == "todo"
        assert "aus Review vom" in _card(page, numbers["gelb"]).locator(".board-review").inner_text()
        assert "rot 1/3" in _card(page, numbers["rot"]).locator(".board-review").inner_text()
        assert _card(page, numbers["laeuft"]).locator(".board-review-symbol.pulse").count() == 1
        assert errors == []
    finally:
        context.close()


def test_running_review_turns_stuck_on_an_open_board_without_any_change(chromium, board_server):
    """Review-B1: ein haengendes Review aendert nichts am Board; das Badge muss trotzdem
    nach 30 Minuten von "laeuft" auf "haengt" wechseln, ohne Neuladen der Seite."""
    number = _ticket_in_review(board_server, "laeuft lange")
    _review(board_server, number, "running")
    context = chromium.new_context()
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    try:
        page.clock.install()
        goto_board(page, board_server, HUMAN)
        badge = _card(page, number).locator(".board-review")
        badge.wait_for(timeout=10000)
        assert badge.get_attribute("data-state") == "running"
        _card(page, number).click()                                    # offene Ticketansicht ebenso
        page.locator("#boardTaskReview .board-review[data-state='running']").wait_for(timeout=10000)
        changes = board_server.human.get("/board/changes").json()["changes"]
        page.clock.fast_forward("31:00")                               # 31 Minuten, Poll-Takt laeuft mit
        page.locator(f"#boardColumns .board-card[data-ref='api#{number}'] .board-review[data-state='stuck']") \
            .wait_for(timeout=10000)
        page.locator("#boardTaskReview .board-review[data-state='stuck']").wait_for(timeout=10000)
        assert board_server.human.get("/board/changes").json()["changes"] == changes   # wirklich keine Aenderung
        assert errors == []
    finally:
        context.close()


def test_task_view_shows_the_review_with_counts(chromium, board_server):
    numbers = _states(board_server)
    context, page, errors = _open_board(chromium, board_server)
    try:
        _card(page, numbers["gelb"]).click()
        badge = page.locator("#boardTaskReview .board-review")
        badge.wait_for(timeout=10000)
        assert "0 blockierend" in badge.inner_text() and "3 Vorschläge" in badge.inner_text()
        page.keyboard.press("Escape")
        assert errors == []
    finally:
        context.close()


def test_human_restarts_a_review_from_the_task_view(chromium, board_server):
    """conclave#145: Knopf "Review neu starten" nur, wo der Server es erlaubt; danach "Review angefordert"."""
    numbers = _states(board_server)
    context, page, errors = _open_board(chromium, board_server)
    try:
        button = page.locator("#boardTaskReviewRequest")
        _card(page, numbers["laeuft"]).click()                         # laeuft gerade: kein Knopf
        page.locator("#boardTaskReview .board-review[data-state='running']").wait_for(timeout=10000)
        assert button.is_hidden()
        page.click("[data-action='board-close-task']")
        _card(page, numbers["gelb"]).click()                           # in todo: kein Knopf
        page.locator("#boardTaskReview .board-review[data-state='rework']").wait_for(timeout=10000)
        assert button.is_hidden()
        page.click("[data-action='board-close-task']")
        _card(page, numbers["gruen"]).click()
        page.locator("#boardTaskReview .board-review[data-state='passed']").wait_for(timeout=10000)
        assert button.is_visible() and button.inner_text() == "Review neu starten"
        button.click()
        page.locator("#boardTaskReview .board-review[data-state='requested']").wait_for(timeout=10000)
        assert "Review angefordert" in page.locator("#boardTaskReview .board-review").inner_text()
        _card(page, numbers["gruen"]).locator(".board-review[data-state='requested']").wait_for(timeout=10000)
        task = board_server.human.get(f"/board/projects/api/tasks/{numbers['gruen']}").json()
        assert (task["status"], task["review"]["state"]) == ("review", "requested")
        assert errors == []
    finally:
        context.close()


def test_header_counts_tickets_waiting_for_approval_and_filters(chromium, board_server):
    numbers = _states(board_server)
    second = _ticket_in_review(board_server, "auch gruen")
    _review(board_server, second, "running")
    _review(board_server, second, "passed", blocking=0, suggestions=1)
    context, page, errors = _open_board(chromium, board_server)
    try:
        hint = page.locator("#boardApprovals")
        hint.wait_for(state="visible", timeout=10000)
        assert "2 Tickets warten auf deine Freigabe" in hint.inner_text()
        hint.click()
        page.wait_for_function("document.querySelectorAll('#boardColumns .board-card').length === 2")
        shown = page.locator("#boardColumns .board-card").evaluate_all("cs => cs.map(c => c.dataset.ref)")
        assert sorted(shown) == sorted([f"api#{numbers['gruen']}", f"api#{second}"])
        hint.click()                                                       # Filter wieder aus
        page.wait_for_function("document.querySelectorAll('#boardColumns .board-card').length > 2")
        assert errors == []
    finally:
        context.close()


def test_agent_token_gets_no_board_and_no_draggable_cards(chromium, board_server):
    """Die Board-Uebersicht ist nur fuer den Menschen (GET /board); mit Agent-Token keine Karten."""
    _states(board_server)
    context = chromium.new_context()
    page = context.new_page()
    try:
        goto_board(page, board_server, AGENT)
        page.locator("#boardColumns .board-error").wait_for(timeout=10000)
        assert page.locator("#boardColumns .board-card").count() == 0
        assert page.locator("#boardApprovals").is_hidden()
    finally:
        context.close()


def test_role_other_than_human_disables_drag_and_drop(chromium, board_server):
    """Rollen-Sperre im Code (P4): ohne Rolle human kein draggable und kein Ablegen."""
    numbers = _states(board_server)
    context, page, errors = _open_board(chromium, board_server)
    try:
        card = _card(page, numbers["gruen"])
        card.wait_for(timeout=10000)
        page.evaluate("() => { _board.role = 'agent'; renderBoard(); renderBoardApprovals(); }")
        assert page.locator("#boardColumns .board-card[draggable='true']").count() == 0
        assert page.locator("#boardApprovals").is_hidden()
        before = board_server.human.get(f"/board/projects/api/tasks/{numbers['gruen']}").json()
        page.evaluate("""ref => { const col = document.querySelector("#boardColumns .board-col[data-status='doing']");
            const dt = new DataTransfer(); dt.setData('text/plain', ref);
            col.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true})); }""",
                      f"api#{numbers['gruen']}")
        page.wait_for_timeout(500)
        after = board_server.human.get(f"/board/projects/api/tasks/{numbers['gruen']}").json()
        assert (after["status"], after["version"]) == (before["status"], before["version"])
        assert errors == []
    finally:
        context.close()


def test_human_can_still_drag_cards(chromium, board_server):
    number = board_server.human.post("/board/tasks", json={"project": "api", "title": "ziehen"}).json()["number"]
    context, page, errors = _open_board(chromium, board_server)
    try:
        card = _card(page, number)
        card.wait_for(timeout=10000)
        assert card.get_attribute("draggable") == "true"
        assert errors == []
    finally:
        context.close()
