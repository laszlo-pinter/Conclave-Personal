"""Gemeinsame Fixtures fuer Browser-Tests (Playwright + Chromium).

Ohne Playwright/Chromium werden Browser-Tests uebersprungen. Mit
``CONCLAVE_REQUIRE_BROWSER=1`` (CI-Job ``ui-browser``) scheitern sie
stattdessen, damit sie nicht unbemerkt ausfallen.
"""

import os
import threading

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
    """Echte Conclave-App (SQLite, leerer Workspace, ohne API-Key) auf einem freien Port."""
    from werkzeug.serving import make_server

    from conclave.api.server import _build_app
    from conclave.cli.config import ConclaveConfig

    root = tmp_path_factory.mktemp("live")
    (root / "workspace").mkdir()
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("CONCLAVE_WORKSPACE", str(root / "workspace"))
        mp.setenv("CONCLAVE_SECRET_KEY_FILE", str(root / "secret.key"))
        mp.setenv("CONCLAVE_BACKUP_DIR", str(root / "backups"))
        app, _ = _build_app(ConclaveConfig(db_path=root / "conclave.db", api_key="", mode="development"))
        server = make_server("127.0.0.1", 0, app, threaded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            thread.join(timeout=5)
