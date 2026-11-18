"""Gemeinsame Fixtures fuer Browser-Tests (Playwright + Chromium).

Ohne Playwright/Chromium werden Browser-Tests uebersprungen. Mit
``CONCLAVE_REQUIRE_BROWSER=1`` (CI-Job ``ui-browser``) scheitern sie
stattdessen, damit sie nicht unbemerkt ausfallen.
"""

import os
import threading
from types import SimpleNamespace

import pytest


def browser_unavailable(reason: str):
    if os.environ.get("CONCLAVE_REQUIRE_BROWSER") == "1":
        pytest.fail(f"Browser-Test erforderlich, aber nicht ausfuehrbar: {reason}")
    pytest.skip(reason)


@pytest.fixture(scope="session")
def chromium():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        browser_unavailable("Playwright ist nicht installiert")
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:  # Chromium nicht installiert
            browser_unavailable(f"Chromium fuer Playwright nicht verfuegbar: {exc}")
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture(scope="session")
def live_server(tmp_path_factory):
    """Echte Conclave-App (SQLite, leerer Workspace, Token aus Token-Datei) auf einem freien Port."""
    from werkzeug.serving import make_server

    from conclave.api.server import _build_app
    from conclave.cli.config import ConclaveConfig

    root = tmp_path_factory.mktemp("live")
    (root / "workspace").mkdir()
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("CONCLAVE_WORKSPACE", str(root / "workspace"))
        mp.setenv("CONCLAVE_SECRET_KEY_FILE", str(root / "secret.key"))
        mp.setenv("CONCLAVE_BACKUP_DIR", str(root / "backups"))
        mp.setenv("CONCLAVE_API_TOKEN_FILE", str(root / "api.token"))
        mp.setenv("CONCLAVE_AGENT_TOKEN_FILE", str(root / "agent.token"))
        mp.setenv("CONCLAVE_REVIEWER_TOKEN_FILE", str(root / "reviewer.token"))
        mp.delenv("CONCLAVE_AGENT_KEY", raising=False)
        mp.delenv("CONCLAVE_REVIEWER_KEY", raising=False)
        mp.delenv("CONCLAVE_API_KEY", raising=False)
        app, config = _build_app(ConclaveConfig(db_path=root / "conclave.db", api_key="", mode="development"))
        server = make_server("127.0.0.1", 0, app, threaded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield SimpleNamespace(url=f"http://127.0.0.1:{server.server_port}", token=config.api_key,
                                  agent_token=config.agent_api_key)
        finally:
            server.shutdown()
            thread.join(timeout=5)


# U1 (conclave#110): Die Board-Tests laufen gegen den Board-Reiter des Studios und gegen die
# eigenstaendige Board-Seite aus dem Kern; beide nutzen dieselbe Ansicht (board.js).
BOARD_SURFACES = ["studio", "page"]
BOARD_TAB = "[data-action='switch-tab'][data-tab='board']"


@pytest.fixture(params=BOARD_SURFACES)
def board_surface(request):
    return request.param


def goto_board(page, server, token):
    """Board oeffnen und mit ``token`` anmelden (Token im Fragment, wie bei ``conclave desktop``)."""
    if server.surface == "page":
        page.goto(f"{server.url}/ui/board#token={token}")
    else:
        page.goto(f"{server.url}/#token={token}")
        page.click(BOARD_TAB)


def reload_board(page, server):
    """Neu laden; angemeldet bleibt der Tab (sessionStorage)."""
    page.reload()
    if server.surface != "page":
        page.click(BOARD_TAB)
