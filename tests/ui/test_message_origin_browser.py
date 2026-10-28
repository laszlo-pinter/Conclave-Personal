"""Z4: Kennzeichen "ueber Agent" an User-Nachrichten im Browser.

Echte App (SQLite) mit Mensch- und Agent-Token. Nur Nachrichten mit
origin=agent bekommen das Kennzeichen; Mensch und unbekannte Herkunft nicht.
"""

import json
import threading
import urllib.request
from types import SimpleNamespace

import pytest

HUMAN = "cvh_mensch-token"
AGENT = "cva_agent-token"


@pytest.fixture
def origin_server(tmp_path, monkeypatch):
    from werkzeug.serving import make_server

    from conclave.api.app import create_app
    from conclave.cli.bootstrap import build_service
    from conclave.cli.config import ConclaveConfig
    from conclave.cli.handler import CLIHandler
    from conclave.infrastructure.auth import StaticKeyAuthService
    from conclave.infrastructure.sqlite.connection import ThreadLocalConnection
    from conclave.infrastructure.sqlite.schema import initialize_schema

    (tmp_path / "workspace").mkdir()
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(tmp_path / "workspace"))
    config = ConclaveConfig(db_path=tmp_path / "conclave.db", api_key=HUMAN, mode="development")
    conn = ThreadLocalConnection(config.db_path)
    initialize_schema(conn)
    service = build_service(config=config, connection=conn)
    conv = service.create_conversation(topic="Herkunft")
    service.add_user_message(conv.id, "Alte Nachricht")          # ohne Zugang: unbekannt
    conn.commit()

    app = create_app(CLIHandler(service), auth_service=StaticKeyAuthService(HUMAN, AGENT),
                     config=config, service=service)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    srv = SimpleNamespace(url=f"http://127.0.0.1:{server.server_port}", conv_id=conv.id)
    try:
        _post(srv, AGENT, "Von cc ueber MCP")
        _post(srv, HUMAN, "Von Laszlo")
        yield srv
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _post(server, token, content):
    req = urllib.request.Request(f"{server.url}/conversations/{server.conv_id}/messages", method="POST",
                                 data=json.dumps({"content": content}).encode(),
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        assert json.loads(resp.read())["origin"] == ("agent" if token == AGENT else "human")


def test_only_agent_messages_carry_the_origin_tag(chromium, origin_server):
    page = chromium.new_page()
    page.add_init_script("window.__csp=[];document.addEventListener('securitypolicyviolation',"
                         "e=>window.__csp.push(e.violatedDirective));")
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    try:
        page.goto(f"{origin_server.url}/#token={HUMAN}")
        page.click(f"[data-action='select-conversation'][data-conversation-id='{origin_server.conv_id}']")
        page.locator("#messages .msg.user").nth(2).wait_for(timeout=10000)

        rows = page.locator("#messages .msg.user")
        assert rows.count() == 3
        tagged = [i for i in range(3) if rows.nth(i).locator(".msg-origin").count()]
        assert tagged == [1]                                   # nur "Von cc ueber MCP"
        assert "Von cc" in rows.nth(1).locator(".msg-content").inner_text()
        tag = rows.nth(1).locator(".msg-origin")
        assert tag.inner_text().strip().lower() in ("über agent", "via agent")
        assert "Agent-Token" in (tag.get_attribute("title") or "") or "agent token" in (tag.get_attribute("title") or "")
        assert page.locator("#messages .msg-origin").count() == 1
        assert errors == [] and page.evaluate("window.__csp") == []
    finally:
        page.close()
