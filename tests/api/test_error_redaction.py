"""R12 (conclave#47): Keine Keys und URLs in Fehlern, Antworten und Logs.

- Gemini bekommt den Key im Header x-goog-api-key, nicht in der URL.
- Provider-Fehler nennen weder URL noch Key; Antworten des Providers landen
  nicht ungekuerzt im Log.
- Fehler gehen zentral uebersetzt an Clients; SSE-Fehler kommen als JSON.
"""

import asyncio
import json
import logging
import sqlite3
from datetime import UTC, datetime
from unittest.mock import MagicMock

import httpx
import pytest

pytest.importorskip("flask")

from conclave.api.app import create_app  # noqa: E402
from conclave.cli.handler import CLIResult  # noqa: E402
from conclave.domain.errors import ProviderError, public_message, redact_secrets  # noqa: E402
from conclave.infrastructure.universal import adapter as adapter_mod  # noqa: E402
from conclave.infrastructure.universal.adapter import UniversalAdapter  # noqa: E402
from conclave.infrastructure.universal.profiles import get_profile  # noqa: E402

KEY = "AIzaSyGEHEIM0123456789abcdefghijklmno"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _conversation():
    from conclave.domain.conversation import Conversation
    from conclave.domain.message import Message, MessageAuthorType
    conv = Conversation(id="c1", status="active", topic="t")
    conv.messages = [Message(id="m1", conversation_id="c1", author_type=MessageAuthorType.USER, author_id=None,
                             content="Hallo", sequence=1, created_at=datetime.now(UTC))]
    return conv


def _participant():
    from conclave.domain.participant import Participant, ParticipantType
    return Participant(id="p1", conversation_id="c1", participant_type=ParticipantType.MODEL, name="P")


def _gemini():
    return UniversalAdapter(api_url=GEMINI_URL, api_key=KEY, model="gemini-2.5-flash",
                            response_path="candidates[0].content.parts[0].text", message_format="gemini",
                            provider_name="gemini")


def _reply(status, payload, calls=None):
    def post(url, **kwargs):
        if calls is not None:
            calls.append((url, kwargs))
        request = httpx.Request("POST", url, params=kwargs.get("params"), headers=kwargs.get("headers"))
        return httpx.Response(status, json=payload, request=request)
    return post


def _logged(caplog):
    return "\n".join(r.getMessage() for r in caplog.records)


# ── Gemini-Key im Header ────────────────────────────────────────────────────

def test_gemini_key_goes_into_the_header():
    profile = get_profile("gemini")
    url, params = profile.build_url(GEMINI_URL, "gemini-2.5-flash", KEY)
    assert KEY not in url and KEY not in json.dumps(params)
    assert profile.build_headers(KEY)["x-goog-api-key"] == KEY


def test_gemini_request_carries_no_key_in_the_url(monkeypatch):
    calls = []
    monkeypatch.setattr(adapter_mod, "_http_post",
                        _reply(200, {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}, calls))
    assert _gemini().complete(_conversation(), _participant()).text == "ok"
    [(url, kwargs)] = calls
    assert KEY not in url and KEY not in json.dumps(kwargs.get("params") or {})
    assert kwargs["headers"]["x-goog-api-key"] == KEY


@pytest.mark.parametrize("status", [400, 403, 500])
def test_gemini_error_contains_no_key_in_exception_or_log(monkeypatch, caplog, status):
    payload = {"error": {"message": f"API key not valid: {KEY}", "status": "INVALID_ARGUMENT"}}
    monkeypatch.setattr(adapter_mod, "_http_post", _reply(status, payload))
    caplog.set_level(logging.DEBUG)
    with pytest.raises(Exception) as e:
        _gemini().complete(_conversation(), _participant())
    text = str(e.value)
    assert KEY not in text and "://" not in text
    assert KEY not in _logged(caplog) and "googleapis.com" not in _logged(caplog)


def test_stream_error_contains_no_url(monkeypatch):
    class Failing:
        def __init__(self, method, url, **kwargs):
            self.request = httpx.Request(method, url, params=kwargs.get("params"))

        def __enter__(self):
            return httpx.Response(502, request=self.request)

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(adapter_mod, "_http_stream", Failing)
    with pytest.raises(httpx.HTTPStatusError) as e:
        list(_gemini().stream(_conversation(), _participant()))
    assert "://" not in str(e.value) and KEY not in str(e.value)


def test_unusable_provider_answer_is_not_logged_or_returned(monkeypatch, caplog):
    monkeypatch.setattr(adapter_mod, "_http_post", _reply(200, {"secret_field": "vertraulicher Inhalt"}))
    caplog.set_level(logging.DEBUG)
    with pytest.raises(ValueError) as e:
        _gemini().complete(_conversation(), _participant())
    assert "vertraulicher Inhalt" not in str(e.value)
    assert "vertraulicher Inhalt" not in _logged(caplog)


def test_transport_errors_name_no_url(monkeypatch):
    def refuse(url, **kwargs):
        raise httpx.ConnectError(f"Verbindung zu {url}?key={KEY} abgelehnt")
    monkeypatch.setattr(adapter_mod, "_http_post", refuse)
    with pytest.raises(httpx.ConnectError) as e:
        _gemini().complete(_conversation(), _participant())
    assert KEY not in str(e.value) and "://" not in str(e.value)


# ── Zentrale Uebersetzung ───────────────────────────────────────────────────

def test_redact_removes_urls_and_keys():
    text = f"Fehler bei https://x.example/v1?key={KEY} mit Bearer sk-abcdef123456 und api_key=xyz"
    out = redact_secrets(text)
    assert KEY not in out and "sk-abcdef123456" not in out and "xyz" not in out and "://" not in out


def test_public_message_hides_unknown_exceptions():
    assert "geheim" not in public_message(RuntimeError("geheim /pfad/zur/datei"))
    assert public_message(ProviderError("gemini", "Timeout")) == "Provider 'gemini': Timeout"


@pytest.fixture
def handler():
    return MagicMock()


@pytest.fixture
def client(handler):
    app = create_app(handler, allow_unauthenticated=True)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_api_error_from_a_failed_call_names_no_url_or_key(client, handler):
    handler.invoke_participant.return_value = CLIResult(
        success=False, message=f"Fehler: Client error for url https://h.example/v1?key={KEY}", data={})
    res = client.post("/conversations/c1/participants/p1/invoke", json={})
    assert res.status_code == 502
    assert KEY not in res.get_data(as_text=True) and "://" not in res.get_json()["error"]


def test_stream_error_is_json_without_details(client, handler):
    def broken(*a, **k):
        yield "Hal"
        raise RuntimeError(f"kaputt bei https://h.example/?key={KEY}")
    handler.stream_participant = broken
    body = client.get("/conversations/c1/participants/p1/stream").get_data(as_text=True)
    [line] = [x for x in body.split("\n") if x.startswith("data: [ERROR]")]
    event = json.loads(line[len("data: [ERROR]"):])
    assert event["type"] == "RuntimeError" and event["error"]
    assert KEY not in body and "h.example" not in body


@pytest.mark.parametrize("route, method, payload", [
    ("/conversations/c1/auto-loop", "auto_loop", {"sequence": ["p1", "p2"]}),
    ("/conversations/c1/orchestrate-parallel-stream", "orchestrate_parallel_stream", {"groups": [["p1"]]}),
])
def test_sse_routes_hide_exception_text(client, handler, route, method, payload):
    def broken(*a, **k):
        raise RuntimeError(f"kaputt bei https://h.example/?key={KEY}")
        yield  # pragma: no cover
    setattr(handler, method, broken)
    body = client.post(route, json=payload).get_data(as_text=True)
    assert '"reason": "error"' in body
    assert KEY not in body and "h.example" not in body


# ── Orchestrator (fuer Agenten erlaubt) ─────────────────────────────────────

def test_parallel_orchestrator_error_names_no_url_or_key():
    from conclave.application.adapter_registry import AdapterRegistry
    from conclave.application.conversation_flow import ConversationFlowService
    from conclave.application.orchestrator import ParallelOrchestrator
    from conclave.domain.participant import ParticipantType
    from conclave.infrastructure.sqlite.conversation_repository import SQLiteConversationRepository
    from conclave.infrastructure.sqlite.message_repository import SQLiteMessageRepository
    from conclave.infrastructure.sqlite.participant_repository import SQLiteParticipantRepository
    from conclave.infrastructure.sqlite.schema import initialize_schema

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    initialize_schema(conn)
    service = ConversationFlowService(
        conversation_repository=SQLiteConversationRepository(conn, autocommit=True),
        message_repository=SQLiteMessageRepository(conn, autocommit=True),
        participant_repository=SQLiteParticipantRepository(conn, autocommit=True),
    )

    class Leaky:
        def complete(self, conversation, participant):
            request = httpx.Request("POST", f"https://h.example/v1?key={KEY}")
            raise httpx.HTTPStatusError(f"Server error for url {request.url}", request=request,
                                        response=httpx.Response(500, request=request))

    registry = AdapterRegistry()
    registry.register("m1", Leaky())
    service.set_adapter_registry(registry)
    conv = service.create_conversation()
    service.register_participant(conv.id, "m1", ParticipantType.MODEL, "M1")
    service.add_user_message(conv.id, "Frage")
    result = asyncio.run(ParallelOrchestrator(service).run(conv.id, groups=[["m1"]]))
    assert not result.success
    assert KEY not in result.error and "://" not in result.error


def test_json_log_masks_keys_in_messages():
    from conclave.infrastructure.log import JsonFormatter
    record = logging.LogRecord("t", logging.ERROR, __file__, 1, "Anfrage mit Bearer %s", ("sk-geheim123456",), None)
    line = JsonFormatter().format(record)
    assert "sk-geheim123456" not in line and "Bearer ***" in line


def test_update_agent_hides_unexpected_errors(client, handler):
    """R12-Review V1: auch ausserhalb der Provider-Pfade kein str(exc) an Clients."""
    handler.get_agent.side_effect = RuntimeError("geheim C:/Users/x/AppData/secret.key")
    res = client.put("/agents/a1", json={"name": "A", "model": "m"})
    assert res.status_code == 400
    assert "geheim" not in res.get_data(as_text=True) and "secret.key" not in res.get_data(as_text=True)
