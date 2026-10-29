"""B5 (conclave#27): Board in der UI (Browser).

Spalten aus der Konfiguration, Karten, Drag & Drop, Ticketansicht mit gefiltertem
Markdown und Herkunft der Kommentare, neues Ticket, Suche und Live-Refresh nach
Aenderungen ueber die API (z. B. durch einen Agenten).
"""

import threading
from types import SimpleNamespace

import httpx
import pytest

HUMAN = "cvh_mensch-token"
AGENT = "cva_agent-token"
EVIL = """## Abnahme

- Tests gruen

<script>window.__pwned = 1</script>
<img src="x" onerror="window.__pwned = 2">
[Klick](javascript:window.__pwned=3)
"""


@pytest.fixture
def board_server(tmp_path, monkeypatch):
    from werkzeug.serving import make_server

    from conclave.api.server import _build_app
    from conclave.cli.config import ConclaveConfig

    (tmp_path / "workspace").mkdir()
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("CONCLAVE_SECRET_KEY_FILE", str(tmp_path / "secret.key"))
    monkeypatch.setenv("CONCLAVE_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("CONCLAVE_API_TOKEN_FILE", str(tmp_path / "api.token"))
    monkeypatch.setenv("CONCLAVE_AGENT_TOKEN_FILE", str(tmp_path / "agent.token"))
    monkeypatch.delenv("CONCLAVE_AGENT_KEY", raising=False)
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
    try:
        yield api
    finally:
        api.human.close()
        api.agent.close()
        server.shutdown()
        thread.join(timeout=5)


def _task(client, **body):
    resp = client.post("/board/tasks", json={"project": "api", "title": "T", **body})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _csp_problems(page):
    """Wie im Viewer-Test: DOMPurify zerlegt `onerror=...` in einem inerten Dokument; Chrome meldet das
    als script-src-attr aus purify.min.js. Ausgefuehrt wird nichts (siehe __pwned)."""
    return [v for v in page.evaluate("window.__csp")
            if not (v.startswith("script-src-attr ") and v.endswith("/static/vendor/purify.min.js"))]


def _open_board(chromium, server):
    page = chromium.new_page()
    page.add_init_script("window.__csp=[];document.addEventListener('securitypolicyviolation',"
                         "e=>window.__csp.push(e.violatedDirective+' '+e.sourceFile));")
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server.url}/#token={HUMAN}")
    page.click("[data-action='switch-tab'][data-tab='board']")
    page.locator("#boardColumns .board-col").first.wait_for(timeout=10000)
    return page, errors


def _card(page, ref):
    return page.locator(f"#boardColumns .board-card[data-ref='{ref}']")


def _column_refs(page, status):
    return page.locator(f"#boardColumns .board-col[data-status='{status}'] .board-card").evaluate_all(
        "cards => cards.map(c => c.dataset.ref)")


def test_columns_and_cards(chromium, board_server):
    _task(board_server.human, title="Entscheidung <b>fett</b>", human=True, tags=["plan"])
    _task(board_server.agent, title="Umsetzen", tags=["b5", "ui"])
    page, errors = _open_board(chromium, board_server)
    try:
        _card(page, "api#2").wait_for(timeout=10000)
        statuses = page.locator("#boardColumns .board-col").evaluate_all("cols => cols.map(c => c.dataset.status)")
        assert statuses == ["todo", "doing", "review", "done"]                   # aus [board] statuses
        assert _column_refs(page, "todo") == ["api#1", "api#2"]
        human = _card(page, "api#1")
        assert human.locator(".board-card-title").inner_text() == "Entscheidung <b>fett</b>"   # als Text
        assert human.locator("b").count() == 0
        assert human.locator(".board-human").is_visible()
        assert _card(page, "api#2").locator(".board-human").count() == 0
        assert _card(page, "api#2").locator(".board-tag").all_inner_texts() == ["b5", "ui"]
        assert errors == [] and _csp_problems(page) == []
    finally:
        page.close()


def test_drag_and_drop_changes_status_and_position(chromium, board_server):
    for title in ("Eins", "Zwei", "Drei"):
        _task(board_server.human, title=title)
    page, errors = _open_board(chromium, board_server)
    try:
        _card(page, "api#3").wait_for(timeout=10000)
        page.drag_and_drop("#boardColumns .board-card[data-ref='api#2']",
                           "#boardColumns .board-col[data-status='review']")
        page.locator("#boardColumns .board-col[data-status='review'] .board-card[data-ref='api#2']").wait_for(
            timeout=10000)
        assert board_server.human.get("/board/projects/api/tasks/2").json()["status"] == "review"

        # Innerhalb der Spalte: api#3 ueber api#1 ziehen
        page.drag_and_drop("#boardColumns .board-card[data-ref='api#3']",
                           "#boardColumns .board-card[data-ref='api#1']", target_position={"x": 20, "y": 2})
        page.wait_for_function("() => [...document.querySelectorAll(\"[data-status='todo'] .board-card\")]"
                               ".map(c => c.dataset.ref).join() === 'api#3,api#1'", timeout=10000)
        tasks = board_server.human.get("/board/tasks", params={"status": "todo"}).json()["tasks"]
        assert [t["ref"] for t in tasks] == ["api#3", "api#1"]
        assert errors == [] and _csp_problems(page) == []
    finally:
        page.close()


def test_task_view_filters_markdown_and_shows_origin(chromium, board_server, board_sample_export):
    _task(board_server.agent, title="Mit Abnahme", description=EVIL)
    board_server.human.post("/board/projects/api/tasks/1/comments", json={"body": "**Freigabe** folgt"})
    board_server.agent.post("/board/projects/api/tasks/1/comments",
                            json={"body": "Commit abc <img src=x onerror=\"window.__pwned=4\">"})
    assert board_server.human.post("/board/import", json=board_sample_export).status_code == 200
    page, errors = _open_board(chromium, board_server)
    try:
        _card(page, "api#1").click()
        desc = page.locator("#boardTaskDesc")
        desc.locator("h2").wait_for(timeout=10000)
        assert page.locator("#boardTaskRef").inner_text() == "api#1"
        assert desc.locator("h2").inner_text() == "Abnahme"
        page.wait_for_timeout(300)
        assert page.evaluate("window.__pwned") is None
        assert page.locator("#overlayBoardTask").locator("script, img, [onerror]").count() == 0
        assert all(not (a.get_attribute("href") or "").lower().startswith("javascript:")
                   for a in desc.locator("a").all())

        comments = page.locator("#boardTaskComments .board-comment")
        assert comments.evaluate_all("cs => cs.map(c => c.dataset.origin)") == ["human", "agent"]
        assert comments.nth(0).locator(".board-origin").inner_text() == "Mensch"
        assert comments.nth(1).locator(".board-origin").inner_text() == "über Agent"
        assert comments.nth(0).locator("strong").inner_text() == "Freigabe"

        # Importierte Kommentare haben keine belegte Herkunft
        page.click("[data-action='board-close-task']")
        page.locator("#boardProject").select_option("conclave")
        assert _card(page, "conclave#7").count() == 0                         # erledigt: ausgeblendet
        page.check("#boardShowDone")
        _card(page, "conclave#7").click()
        page.locator("#boardTaskComments .board-comment").first.wait_for(timeout=10000)
        origins = page.locator("#boardTaskComments .board-origin").all_inner_texts()
        assert origins and set(origins) == {"unbekannt"}
        assert page.evaluate("originLabel('system')") == "Zweitmeinung (Modell)"
        assert errors == [] and _csp_problems(page) == []
    finally:
        page.close()


def test_status_change_and_comment_from_task_view(chromium, board_server):
    _task(board_server.agent, title="Pruefen")
    page, errors = _open_board(chromium, board_server)
    try:
        _card(page, "api#1").click()
        page.locator("#boardTaskStatus").select_option("done")
        page.locator("#boardColumns .board-col[data-status='done']").wait_for(timeout=10000)
        page.wait_for_function("() => !document.querySelector(\"[data-status='todo'] [data-ref='api#1']\")",
                               timeout=10000)
        page.fill("#boardCommentBody", "Abgenommen")
        page.click("[data-action='board-comment']")
        page.locator("#boardTaskComments .board-comment").first.wait_for(timeout=10000)
        task = board_server.human.get("/board/projects/api/tasks/1").json()
        assert task["status"] == "done"
        assert [(c["origin"], c["body"]) for c in task["comments"]] == [("human", "Abgenommen")]
        events = board_server.human.get("/board/projects/api/tasks/1/history").json()["history"]
        assert [(e["field"], e["new"], e["origin"]) for e in events] == [("status", "done", "human")]
        assert page.locator("#boardTaskHistory .board-event").count() == 1
        assert errors == [] and _csp_problems(page) == []
    finally:
        page.close()


def test_new_ticket_and_search(chromium, board_server):
    _task(board_server.human, title="Alt", description="nichts")
    page, errors = _open_board(chromium, board_server)
    try:
        page.click("[data-action='board-new']")
        page.fill("#boardNewTitle", "Neu aus der UI")
        page.fill("#boardNewDesc", "Suchwort **zebra**")
        page.fill("#boardNewTags", "ui, b5")
        page.check("#boardNewHuman")
        page.click("[data-action='board-create']")
        _card(page, "api#2").wait_for(timeout=10000)
        task = board_server.human.get("/board/projects/api/tasks/2").json()
        assert (task["title"], task["tags"], task["human"], task["status"]) == ("Neu aus der UI", ["ui", "b5"],
                                                                               True, "todo")

        page.fill("#boardSearch", "zebra")
        page.wait_for_function("() => !document.querySelector(\"#boardColumns [data-ref='api#1']\")", timeout=10000)
        assert _column_refs(page, "todo") == ["api#2"]
        page.fill("#boardSearch", "")
        _card(page, "api#1").wait_for(timeout=10000)
        assert errors == [] and _csp_problems(page) == []
    finally:
        page.close()


def test_live_refresh_after_api_changes(chromium, board_server):
    _task(board_server.human, title="Offen")
    page, errors = _open_board(chromium, board_server)
    try:
        _card(page, "api#1").click()
        page.locator("#boardTaskRef").wait_for(timeout=10000)

        # Ein Agent arbeitet ueber die API; die UI zieht ohne Neuladen nach
        _task(board_server.agent, title="Vom Agenten")
        board_server.agent.post("/board/projects/api/tasks/1/comments", json={"body": "Branch board"})
        assert board_server.agent.patch("/board/projects/api/tasks/1", json={"status": "review"}).status_code == 200
        _card(page, "api#2").wait_for(timeout=15000)
        page.locator("#boardTaskComments .board-comment[data-origin='agent']").wait_for(timeout=15000)
        assert page.locator("#boardTaskStatus").input_value() == "review"
        assert _column_refs(page, "review") == ["api#1"]
        assert errors == [] and _csp_problems(page) == []
    finally:
        page.close()
