"""P6 (conclave#61): Banner "Anweisung vom Menschen" und Knopf "Agenten pausieren" (Browser).

Die UI hat ein Farbschema; geprueft wird mit hell und dunkel eingestelltem Browser, dass das
Banner lesbar ist (Text neben der Farbe, Kontrast) und dass Steuertickets nicht als Karte
in den Spalten stehen.
"""

import threading
from types import SimpleNamespace

import httpx
import pytest

HUMAN = "cvh_mensch-token"
AGENT = "cva_agent-token"


@pytest.fixture
def board_server(tmp_path, monkeypatch):
    from werkzeug.serving import make_server

    from conclave.api.server import _build_app
    from conclave.cli.config import ConclaveConfig

    (tmp_path / "workspace").mkdir()
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("CONCLAVE_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.delenv("CONCLAVE_API_KEY", raising=False)
    app, _ = _build_app(ConclaveConfig(db_path=tmp_path / "conclave.db", api_key=HUMAN, agent_api_key=AGENT,
                                       mode="development"))
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    api = SimpleNamespace(url=url, human=httpx.Client(base_url=url, headers={"Authorization": f"Bearer {HUMAN}"}),
                          agent=httpx.Client(base_url=url, headers={"Authorization": f"Bearer {AGENT}"}))
    assert api.human.post("/board/projects", json={"slug": "api", "name": "API"}).status_code == 201
    assert api.human.post("/board/tasks", json={"project": "api", "title": "Arbeit"}).status_code == 201
    try:
        yield api
    finally:
        api.human.close()
        api.agent.close()
        server.shutdown()
        thread.join(timeout=5)


def _open_board(browser, server, scheme):
    context = browser.new_context(color_scheme=scheme)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server.url}/#token={HUMAN}")
    page.click("[data-action='switch-tab'][data-tab='board']")
    page.locator("#boardColumns .board-col").first.wait_for(timeout=10000)
    return context, page, errors


def _luminance(rgb: str) -> float:
    parts = [int(float(x)) for x in rgb[rgb.index("(") + 1:rgb.index(")")].split(",")[:3]]

    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in parts)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_pause_button_shows_the_banner_and_closing_removes_it(chromium, board_server, scheme):
    context, page, errors = _open_board(chromium, board_server, scheme)
    try:
        assert page.locator("#boardControl").is_hidden()
        page.click("[data-action='board-pause']")
        banner = page.locator("#boardControl")
        banner.locator(".board-control-item.pause").wait_for(timeout=10000)
        assert "Anweisung vom Menschen" in banner.inner_text()
        assert banner.locator(".board-control-kind").inner_text() == "Pause"          # Text neben der Farbe
        assert board_server.agent.post("/board/next", json={}).json()["paused"] is True
        # Steuertickets erscheinen nicht als Karte
        assert page.locator("#boardColumns .board-card[data-ref='api#2']").count() == 0
        # lesbar: Kontrast zwischen Text und Seitenhintergrund
        text = page.evaluate("getComputedStyle(document.querySelector('.board-control-reason')).color")
        bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
        l1, l2 = sorted((_luminance(text), _luminance(bg)), reverse=True)
        assert (l1 + 0.05) / (l2 + 0.05) >= 4.5, (scheme, text, bg)
        page.click("[data-action='board-close-control'][data-ref='api#2']")
        banner.wait_for(state="hidden", timeout=10000)
        assert board_server.agent.post("/board/next", json={}).json()["task"]["ref"] == "api#1"
        assert errors == []
    finally:
        context.close()


def test_acknowledged_hint_shows_who_acknowledged(chromium, board_server):
    assert board_server.human.post("/board/tasks", json={
        "project": "api", "title": "Ab jetzt zuerst die Tests", "kind": "control", "control": "hint",
        "scope": "all"}).status_code == 201
    context, page, errors = _open_board(chromium, board_server, "dark")
    try:
        item = page.locator("#boardControl .board-control-item.hint")
        item.wait_for(timeout=10000)
        assert "noch nicht quittiert" in item.inner_text()
        assert board_server.agent.post("/board/projects/api/tasks/2/comments",
                                       json={"body": "Verstanden", "author_name": "cc"}).status_code == 201
        page.locator("#boardControl .board-control-ack", has_text="quittiert von cc").wait_for(timeout=15000)
        assert errors == []
    finally:
        context.close()
