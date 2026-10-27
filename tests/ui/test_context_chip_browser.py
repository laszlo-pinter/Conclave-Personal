"""K3: Kontext-Chip unter Modellantworten im Browser.

Echte App (SQLite) mit echtem UniversalAdapter; nur httpx ist gefaelscht.
Kuerzungslimit 5, damit der Chip eine echte Kuerzung zeigt.
"""

import json
import threading
import urllib.request
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

import conclave.infrastructure.universal.adapter as universal

API_URL = "https://api.openai.com/v1/chat/completions"
HTML_NAME = "<b>boese</b>.md"


def _ok(*args, **kwargs):
    return httpx.Response(200, json={
        "choices": [{"message": {"content": "Antwort vom Modell"}}],
        "usage": {"prompt_tokens": 321, "completion_tokens": 12},
    }, request=httpx.Request("POST", API_URL))


class _Stream:
    def __init__(self, *args, **kwargs):
        self._lines = [
            'data: {"choices":[{"delta":{"content":"Gestreamt"}}]}', "",
            'data: {"choices":[],"usage":{"prompt_tokens":77,"completion_tokens":3}}', "",
            "data: [DONE]", "",
        ]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_lines(self):
        return iter(self._lines)


def _wait_until(page, expression, timeout=10.0):
    """Wie wait_for_function, aber ohne eval im Seitenkontext (die CSP verbietet es)."""
    import time
    deadline = time.monotonic() + timeout
    while not page.evaluate(expression):
        assert time.monotonic() < deadline, f"Zeitueberschreitung: {expression}"
        page.wait_for_timeout(50)


@pytest.fixture
def context_server(tmp_path, monkeypatch):
    from werkzeug.serving import make_server

    from conclave.api.app import create_app
    from conclave.application.adapter_registry import AdapterRegistry
    from conclave.cli.bootstrap import build_service
    from conclave.cli.config import ConclaveConfig
    from conclave.cli.handler import CLIHandler
    from conclave.domain.participant import ParticipantType
    from conclave.infrastructure.auth import StaticKeyAuthService
    from conclave.infrastructure.sqlite.connection import ThreadLocalConnection
    from conclave.infrastructure.sqlite.schema import initialize_schema
    from conclave.infrastructure.universal.resilient import ResilientAdapter

    (tmp_path / "workspace").mkdir()
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setattr(universal, "MAX_MESSAGES", 5)
    config = ConclaveConfig(db_path=tmp_path / "conclave.db", api_key="test-token", mode="development")
    conn = ThreadLocalConnection(config.db_path)
    initialize_schema(conn)
    service = build_service(config=config, connection=conn)
    registry = AdapterRegistry()
    registry.register("p1", ResilientAdapter(UniversalAdapterFactory()))
    service.set_adapter_registry(registry)

    conv = service.create_conversation(topic="Kontext-Test")
    service.register_participant(conversation_id=conv.id, participant_id="p1",
                                 participant_type=ParticipantType.MODEL, name="Modell")
    service.set_rules(conv.id, f"context_files: {HTML_NAME}")
    service.add_user_message(conv.id, "Aufgabe: bitte zusammenfassen")
    for i in range(2, 12):
        service.add_user_message(conv.id, f"Beitrag {i}")
    conn.commit()

    app = create_app(CLIHandler(service), auth_service=StaticKeyAuthService(config.api_key),
                     config=config, service=service)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with patch("httpx.post", _ok), patch("httpx.stream", _Stream):
            yield SimpleNamespace(url=f"http://127.0.0.1:{server.server_port}",
                                  token=config.api_key, conv_id=conv.id)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def UniversalAdapterFactory():
    return universal.UniversalAdapter(api_url=API_URL, api_key="k", model="m")


def _post(server, path):
    req = urllib.request.Request(server.url + path, method="POST", data=b"{}",
                                 headers={"Authorization": f"Bearer {server.token}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _open_conversation(chromium, server):
    page = chromium.new_page()
    page.add_init_script("window.__csp=[];document.addEventListener('securitypolicyviolation',"
                         "e=>window.__csp.push(e.violatedDirective));")
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server.url}/#token={server.token}")
    page.click(f"[data-action='select-conversation'][data-conversation-id='{server.conv_id}']")
    return page, errors


def test_chip_shows_truncation_and_details_as_text(chromium, context_server):
    invoked = _post(context_server, f"/conversations/{context_server.conv_id}/participants/p1/invoke")
    assert invoked["context"]["messages_sent"] == 5

    page, errors = _open_conversation(chromium, context_server)
    try:
        chip = page.locator("#messages .msg.model .ctx-chip").first
        chip.wait_for(timeout=10000)
        text = chip.inner_text()
        assert "5/11" in text
        assert "321" in text                      # abgerechnet
        classes = chip.get_attribute("class")
        assert "truncated" in classes and "strong" in classes   # mehr als die Haelfte ausgelassen

        chip.click()
        details = page.locator(".ctx-details")
        _wait_until(page, "() => document.querySelector('.ctx-details .ctx-row') !== null")
        detail_text = details.inner_text()
        assert "#2" in detail_text and "#7" in detail_text      # ausgelassener Bereich
        assert HTML_NAME in detail_text                          # Dateiname als Text ...
        assert page.locator(".ctx-details b").count() == 0       # ... nicht als HTML

        page.click(".ctx-details [data-action='jump-to-message']")
        _wait_until(page, "() => document.querySelector('#messages .msg[data-seq=\"2\"]')"
                          ".classList.contains('flash')")

        chip.click()                                              # zuklappen
        assert page.locator(".ctx-details").count() == 0

        assert page.evaluate("window.__csp") == []
        assert errors == []
    finally:
        page.close()


def test_chip_appears_after_stream(chromium, context_server):
    page, errors = _open_conversation(chromium, context_server)
    try:
        _wait_until(page, "() => [...document.querySelectorAll('#pSel option')].some(o => o.value === 'p1')")
        page.select_option("#pSel", "p1")
        page.click("[data-action='stream-p']")
        _wait_until(page, "() => [...document.querySelectorAll('#messages .ctx-chip')]"
                          ".some(c => c.textContent.includes('77'))")
        assert page.evaluate("window.__csp") == []
        assert errors == []
    finally:
        page.close()


def test_chip_appears_in_auto_loop(chromium, context_server):
    page, errors = _open_conversation(chromium, context_server)
    try:
        page.click("[data-action='open-autoloop']")
        page.fill("#loopSeq", "p1")
        page.fill("#loopRounds", "1")
        page.click("[data-action='run-autoloop']")
        _wait_until(page, "() => document.querySelectorAll('#messages .msg.model .ctx-chip').length >= 1")
        assert "321" in page.locator("#messages .msg.model .ctx-chip").last.inner_text()
        assert page.evaluate("window.__csp") == []
        assert errors == []
    finally:
        page.close()
