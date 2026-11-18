"""U2 (conclave#111): Im Board-Modus fuehrt / im Browser auf die Board-Seite, angemeldet mit dem Token
aus dem Link (das Fragment bleibt bei der Weiterleitung erhalten); das Studio laedt nicht."""

import threading

import httpx
import pytest

HUMAN, AGENT = "cvh_modus-mensch", "cva_modus-agent"


@pytest.fixture
def board_mode_server(tmp_path, monkeypatch):
    from werkzeug.serving import make_server

    from conclave.api.server import _build_app
    from conclave.cli.config import ConclaveConfig, UiSettings

    (tmp_path / "workspace").mkdir()
    for name, value in (("CONCLAVE_WORKSPACE", "workspace"), ("CONCLAVE_SECRET_KEY_FILE", "secret.key"),
                        ("CONCLAVE_BACKUP_DIR", "backups"), ("CONCLAVE_API_TOKEN_FILE", "api.token"),
                        ("CONCLAVE_AGENT_TOKEN_FILE", "agent.token")):
        monkeypatch.setenv(name, str(tmp_path / value))
    monkeypatch.delenv("CONCLAVE_API_KEY", raising=False)
    app, _ = _build_app(ConclaveConfig(db_path=tmp_path / "c.db", api_key=HUMAN, agent_api_key=AGENT,
                                       mode="development", ui=UiSettings("board")))
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    with httpx.Client(base_url=url, headers={"Authorization": f"Bearer {HUMAN}"}) as human:
        assert human.post("/board/v1/projects", json={"slug": "api", "name": "API"}).status_code == 201
        assert human.post("/board/v1/tasks", json={"project": "api", "title": "Erstes"}).status_code == 201
    try:
        yield url
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_root_opens_the_board_page_signed_in(chromium, board_mode_server):
    page = chromium.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    try:
        page.goto(f"{board_mode_server}/#token={HUMAN}")
        page.locator("#boardColumns .board-card[data-ref='api#1']").wait_for(timeout=10000)
        assert page.url == f"{board_mode_server}/ui/board"            # Fragment entfernt, Seite gewechselt
        assert page.locator(".sb-tab").count() == 0                     # kein Studio
        assert page.inner_text("#boardPageLogin") == "Abmelden"
        assert errors == []
    finally:
        page.close()
