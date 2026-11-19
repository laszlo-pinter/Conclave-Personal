"""U4 (conclave#130): Projekte in der Board-Seite und im Board-Reiter des Studios verwalten.

Anlegen, umbenennen und ein leeres Projekt loeschen; ein Projekt mit Tickets bietet kein Loeschen an,
und der Server lehnt es auch dann ab, wenn kurz vorher ein Ticket dazukommt. Mit Agent-Token keine
Schaltflaeche.
"""

import threading
from types import SimpleNamespace

import httpx
import pytest

from tests.ui.conftest import goto_board

HUMAN = "cvh_mensch-token"
AGENT = "cva_agent-token"


@pytest.fixture
def board_server(tmp_path, monkeypatch, board_surface):
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
    api = SimpleNamespace(surface=board_surface, url=url,
                          human=httpx.Client(base_url=url, headers={"Authorization": f"Bearer {HUMAN}"}),
                          agent=httpx.Client(base_url=url, headers={"Authorization": f"Bearer {AGENT}"}))
    try:
        yield api
    finally:
        api.human.close()
        api.agent.close()
        server.shutdown()
        thread.join(timeout=5)


def _open(chromium, server, token=HUMAN):
    context = chromium.new_context()
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("dialog", lambda d: d.accept())                      # Rueckfrage beim Loeschen bestaetigen
    goto_board(page, server, token)
    return context, page, errors


def _row(page, slug):
    return page.locator(f"#boardProjectsList .board-project-row[data-slug='{slug}']")


def _projects(server):
    return {p["slug"]: p["name"] for p in server.human.get("/board/v1").json()["projects"]}


def test_create_rename_and_delete_an_empty_project(chromium, board_server):
    context, page, errors = _open(chromium, board_server)
    try:
        # Ohne Projekte zeigt das Board dem Menschen den Weg zum Anlegen
        page.wait_for_function("() => document.getElementById('boardColumns').textContent.includes('Projekte')",
                               timeout=10000)
        page.click("#boardProjects")
        page.locator("#overlayBoardProjects.open").wait_for(timeout=5000)
        page.locator("#boardProjectsList .surface-empty").wait_for(timeout=5000)

        page.fill("#boardProjectSlug", "api")
        page.fill("#boardProjectName", "API")
        page.click("[data-action='board-project-create']")
        _row(page, "api").wait_for(timeout=5000)
        page.fill("#boardProjectSlug", "leer")
        page.fill("#boardProjectName", "Leer")
        page.click("[data-action='board-project-create']")
        _row(page, "leer").wait_for(timeout=5000)
        assert _projects(board_server) == {"api": "API", "leer": "Leer"}
        assert page.locator("#boardProject option[value='leer']").count() == 1     # Filter kennt es sofort

        # Doppelter Kurzname: Fehlermeldung, nichts angelegt
        page.fill("#boardProjectSlug", "api")
        page.fill("#boardProjectName", "Noch einmal")
        page.click("[data-action='board-project-create']")
        page.locator(".toast.err").first.wait_for(timeout=5000)
        assert _projects(board_server)["api"] == "API"

        _row(page, "api").locator(".board-project-name").fill("API-Dienst")
        _row(page, "api").locator("[data-action='board-project-rename']").click()
        page.wait_for_function("() => [...document.querySelectorAll('#boardProject option')]"
                               ".some(o => o.textContent === 'API-Dienst (api)')", timeout=5000)
        assert _projects(board_server)["api"] == "API-Dienst"

        _row(page, "leer").locator("[data-action='board-project-delete']").click()
        _row(page, "leer").wait_for(state="detached", timeout=5000)
        assert _projects(board_server) == {"api": "API-Dienst"}
        assert errors == []
    finally:
        context.close()


def test_project_with_tickets_cannot_be_deleted(chromium, board_server):
    assert board_server.human.post("/board/v1/projects", json={"slug": "api", "name": "API"}).status_code == 201
    assert board_server.human.post("/board/v1/projects", json={"slug": "fast-leer", "name": "F"}).status_code == 201
    assert board_server.human.post("/board/v1/projects", json={"slug": "plan", "name": "Plan"}).status_code == 201
    assert board_server.human.post("/board/v1/projects/plan/initiatives",
                                   json={"slug": "sich", "title": "Sicherheit"}).status_code == 201
    done = board_server.agent.post("/board/v1/tasks", json={"project": "api", "title": "Alt"}).json()
    assert board_server.human.patch(f"/board/v1/projects/api/tasks/{done['number']}",
                                    json={"status": "done"}).status_code == 200
    context, page, errors = _open(chromium, board_server)
    try:
        page.locator("#boardColumns .board-col").first.wait_for(timeout=10000)
        page.click("#boardProjects")
        _row(page, "api").wait_for(timeout=5000)
        # Auch ein erledigtes Ticket zaehlt: kein Loeschen, stattdessen die Anzahl
        assert _row(page, "api").locator("[data-action='board-project-delete']").count() == 0
        assert _row(page, "api").locator(".board-project-count").inner_text() == "1 Ticket(s)"
        # Ein Projekt nur mit Vorhaben gilt nicht als leer (Review V2)
        assert _row(page, "plan").locator("[data-action='board-project-delete']").count() == 0
        assert _row(page, "plan").locator(".board-project-count").inner_text() == "1 Vorhaben"

        # Ein Agent legt ein Ticket an, waehrend der Dialog offen ist: Der Server lehnt das Loeschen ab
        assert board_server.agent.post("/board/v1/tasks", json={"project": "fast-leer", "title": "X"}).status_code == 201
        _row(page, "fast-leer").locator("[data-action='board-project-delete']").click()
        page.locator(".toast.err").first.wait_for(timeout=5000)
        _row(page, "fast-leer").locator(".board-project-count").wait_for(timeout=5000)
        assert set(_projects(board_server)) == {"api", "fast-leer", "plan"}
        assert board_server.human.get("/board/v1/projects/fast-leer/tasks/1").status_code == 200
        assert errors == []
    finally:
        context.close()


def test_agent_token_has_no_project_buttons(chromium, board_server):
    assert board_server.human.post("/board/v1/projects", json={"slug": "api", "name": "API"}).status_code == 201
    context, page, _errors = _open(chromium, board_server, AGENT)
    try:
        page.locator("#boardColumns .board-error").wait_for(timeout=10000)
        assert page.locator("#boardProjects").is_hidden()
        # Auch wer die Ansicht von Hand aufruft, kommt nicht weiter: openBoardProjects prueft die Rolle
        page.evaluate("() => openBoardProjects()")
        assert page.locator("#overlayBoardProjects.open").count() == 0
        assert board_server.agent.post("/board/v1/projects", json={"slug": "x", "name": "X"}).status_code == 403
    finally:
        context.close()
