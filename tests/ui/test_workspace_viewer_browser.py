"""conclave#14: Viewer fuer Workspace-Dateien im Files-Bereich (Browser).

Markdown erscheint formatiert und gefiltert (DOMPurify): eingebettete Skripte,
Event-Handler und javascript:-Links wirken nicht, die CSP bleibt unverletzt.
"""

import threading
from types import SimpleNamespace

import pytest

TOKEN = "cvh_mensch-token"
MARKDOWN = """# Titel im Viewer

- Punkt eins
- Punkt zwei

```python
print("hallo")
```

<script>window.__pwned = 1</script>
<img src="x" onerror="window.__pwned = 2">
[Klick](javascript:window.__pwned=3)
"""


@pytest.fixture
def viewer_server(tmp_path, monkeypatch):
    from werkzeug.serving import make_server

    from conclave.api.app import create_app
    from conclave.cli.bootstrap import build_service
    from conclave.cli.config import ConclaveConfig
    from conclave.cli.handler import CLIHandler
    from conclave.infrastructure.auth import StaticKeyAuthService
    from conclave.infrastructure.sqlite.connection import ThreadLocalConnection
    from conclave.infrastructure.sqlite.schema import initialize_schema

    ws = tmp_path / "workspace"
    (ws / "notizen").mkdir(parents=True)
    (ws / "notizen" / "plan.md").write_text(MARKDOWN, encoding="utf-8")
    (ws / "liesmich.txt").write_text("Nur <b>Text</b>, kein HTML.", encoding="utf-8")
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(ws))
    config = ConclaveConfig(db_path=tmp_path / "conclave.db", api_key=TOKEN, mode="development")
    conn = ThreadLocalConnection(config.db_path)
    initialize_schema(conn)
    service = build_service(config=config, connection=conn)
    app = create_app(CLIHandler(service), auth_service=StaticKeyAuthService(TOKEN), config=config, service=service)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield SimpleNamespace(url=f"http://127.0.0.1:{server.server_port}")
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _csp_problems(page):
    """CSP-Berichte ohne den einen erwarteten: DOMPurify zerlegt `onerror=...` in einem inerten
    Dokument; Chrome meldet den Inline-Handler dabei als blockiert (script-src-attr, Quelle
    purify.min.js), danach entfernt DOMPurify das Attribut. Ausgefuehrt wird nichts (siehe __pwned)."""
    return [v for v in page.evaluate("window.__csp")
            if not (v.startswith("script-src-attr ") and v.endswith("/static/vendor/purify.min.js"))]


def _open_files(chromium, server):
    page = chromium.new_page()
    page.add_init_script("window.__csp=[];document.addEventListener('securitypolicyviolation',"
                         "e=>window.__csp.push(e.violatedDirective+' '+e.sourceFile));")
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server.url}/#token={TOKEN}")
    page.click("[data-action='switch-tab'][data-tab='workspace']")
    page.locator("#workspaceMainList [data-action='open-workspace-file']").first.wait_for(timeout=10000)
    return page, errors


def test_markdown_is_rendered_filtered_and_switchable(chromium, viewer_server):
    page, errors = _open_files(chromium, viewer_server)
    try:
        page.click("#workspaceMainList [data-action='open-workspace-file'][data-path='notizen/plan.md']")
        body = page.locator("#wsViewerBody")
        body.locator("h1").wait_for(timeout=10000)
        assert page.locator("#wsViewer").is_visible()
        assert page.locator("#wsViewerName").inner_text() == "notizen/plan.md"
        assert body.locator("h1").inner_text() == "Titel im Viewer"
        assert body.locator("li").count() == 2
        assert "hallo" in body.locator("pre code").inner_text()

        # Angriffe aus der Datei wirken nicht
        page.wait_for_timeout(300)
        assert page.evaluate("window.__pwned") is None
        assert body.locator("script, img, [onerror]").count() == 0
        assert all(not (a.get_attribute("href") or "").lower().startswith("javascript:")
                   for a in body.locator("a").all())

        # Umschalter: Quelltext und zurueck
        page.click("#wsViewerMode")
        assert "# Titel im Viewer" in body.locator("pre code").inner_text()
        assert body.locator("h1").count() == 0
        page.click("#wsViewerMode")
        assert body.locator("h1").count() == 1

        assert errors == [] and _csp_problems(page) == []
    finally:
        page.close()


def test_text_file_is_shown_as_text_and_insert_still_works(chromium, viewer_server):
    page, errors = _open_files(chromium, viewer_server)
    try:
        page.click("#workspaceMainList [data-action='open-workspace-file'][data-path='liesmich.txt']")
        code = page.locator("#wsViewerBody pre code")
        code.wait_for(timeout=10000)
        assert code.inner_text() == "Nur <b>Text</b>, kein HTML."
        assert page.locator("#wsViewerBody b").count() == 0
        assert page.locator("#wsViewerMode").is_hidden()            # Umschalter nur bei Markdown

        page.click("[data-action='ws-viewer-insert']")
        assert page.locator("#msgInput").input_value().strip() == "@workspace/liesmich.txt"

        page.click("[data-action='switch-tab'][data-tab='workspace']")
        page.click("[data-action='ws-viewer-close']")
        assert page.locator("#wsViewer").is_hidden()
        assert errors == [] and _csp_problems(page) == []
    finally:
        page.close()


def test_missing_file_shows_error_as_text(chromium, viewer_server):
    page, errors = _open_files(chromium, viewer_server)
    try:
        page.evaluate("openWorkspaceFile('gibt/es/nicht.md')")
        err = page.locator("#wsViewerBody.ws-viewer-error")
        err.wait_for(timeout=10000)
        assert err.inner_text().strip()
        assert errors == [] and _csp_problems(page) == []
    finally:
        page.close()
