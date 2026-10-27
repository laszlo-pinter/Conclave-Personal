"""K2: Kontext-Reports werden gespeichert und ueber die API ausgegeben.

Echter Service (SQLite), echter UniversalAdapter; nur httpx ist gefaelscht.
"""

import json
import sqlite3
from unittest.mock import patch

import httpx
import pytest

pytest.importorskip("flask")

from conclave.api.app import create_app
from conclave.application.adapter_registry import AdapterRegistry
from conclave.application.conversation_flow import ConversationFlowService
from conclave.application.data_export_service import DataExportService
from conclave.cli.handler import CLIHandler
from conclave.domain.participant import ParticipantType
from conclave.infrastructure.migrations import run_migrations
from conclave.infrastructure.sqlite.context_report_repository import SQLiteContextReportRepository
from conclave.infrastructure.sqlite.conversation_repository import SQLiteConversationRepository
from conclave.infrastructure.sqlite.message_repository import SQLiteMessageRepository
from conclave.infrastructure.sqlite.participant_repository import SQLiteParticipantRepository
from conclave.infrastructure.sqlite.run_repository import SQLiteRunRepository
from conclave.infrastructure.sqlite.schema import initialize_schema
from conclave.infrastructure.universal.adapter import UniversalAdapter
from conclave.infrastructure.universal.resilient import ResilientAdapter

API_URL = "https://api.openai.com/v1/chat/completions"


def _ok(text="Antwort", usage=(42, 7)):
    return httpx.Response(200, json={
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1]},
    }, request=httpx.Request("POST", API_URL))


def _http_error(status):
    return httpx.Response(status, json={"error": {"message": "kaputt"}}, request=httpx.Request("POST", API_URL))


def _sse(*chunks):
    lines = []
    for chunk in chunks:
        lines += [f"data: {json.dumps(chunk)}", ""]
    return lines + ["data: [DONE]", ""]


class _StreamResponse:
    def __init__(self, lines):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_lines(self):
        return iter(self._lines)


class Env:
    def __init__(self, conn, service, handler, conv_id, reports, runs):
        self.conn, self.service, self.handler = conn, service, handler
        self.conv_id, self.reports, self.runs = conv_id, reports, runs

    def client(self):
        app = create_app(self.handler)
        app.config["TESTING"] = True
        return app.test_client()


@pytest.fixture
def env():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    initialize_schema(conn)
    service = ConversationFlowService(
        conversation_repository=SQLiteConversationRepository(conn, autocommit=True),
        message_repository=SQLiteMessageRepository(conn, autocommit=True),
        participant_repository=SQLiteParticipantRepository(conn, autocommit=True),
    )
    runs = SQLiteRunRepository(conn)
    reports = SQLiteContextReportRepository(conn, autocommit=True)
    service.set_run_repository(runs)
    service.set_context_report_repository(reports)
    registry = AdapterRegistry()
    for pid in ("p1", "p2"):
        registry.register(pid, ResilientAdapter(
            UniversalAdapter(api_url=API_URL, api_key="k", model="m"), sleep_fn=lambda s: None))
    service.set_adapter_registry(registry)
    conv = service.create_conversation()
    for pid in ("p1", "p2"):
        service.register_participant(conversation_id=conv.id, participant_id=pid,
                                     participant_type=ParticipantType.MODEL, name=pid.upper())
    service.add_user_message(conv.id, "Frage")
    return Env(conn, service, CLIHandler(service), conv.id, reports, runs)


def _model_messages(env):
    return [m for m in env.service.load_conversation(env.conv_id).messages if m.author_id]


# ── Speicherung ──────────────────────────────────────────────────────────

def test_invoke_saves_report_linked_to_message_and_run(env):
    with patch("httpx.post", return_value=_ok()):
        env.service.invoke_participant(env.conv_id, "p1")
    message = _model_messages(env)[-1]
    record = env.reports.get_by_message(message.id)
    run = env.runs.list_by_conversation(env.conv_id)[0]
    assert record.run_id == run.id
    assert (record.input_tokens, record.output_tokens) == (42, 7)
    assert record.report.messages_sent == 1
    assert record.report.adapter == "universal"


def test_stream_saves_report_with_stream_usage(env):
    final = {"choices": [], "usage": {"prompt_tokens": 9, "completion_tokens": 2}}
    lines = _sse({"choices": [{"delta": {"content": "Hallo"}}]}, final)
    with patch("httpx.stream", lambda *a, **k: _StreamResponse(lines)):
        assert "".join(env.service.stream_participant(env.conv_id, "p1")) == "Hallo"
    record = env.reports.get_by_message(_model_messages(env)[-1].id)
    assert (record.input_tokens, record.output_tokens) == (9, 2)
    assert record.run_id is not None


@pytest.mark.parametrize("responses, attempts", [
    ([_http_error(400)], 1),                     # permanenter Fehler, kein Retry
    ([_http_error(503)] * 4, 4),                 # Retries erschoepft -> ProviderUnavailable
])
def test_failed_call_saves_report_without_message(env, responses, attempts):
    with patch("httpx.post", side_effect=list(responses)):
        with pytest.raises(Exception):
            env.service.invoke_participant(env.conv_id, "p1")
    records = env.reports.list_by_conversation(env.conv_id)
    assert len(records) == 1
    record = records[0]
    assert record.message_id is None
    failed_run = env.runs.get(record.run_id)
    assert failed_run.status == "failed"
    assert record.report.attempts == attempts
    assert record.input_tokens is None


def test_parallel_orchestration_links_reports_to_messages(env):
    with patch("httpx.post", side_effect=lambda *a, **k: _ok()):
        result = env.handler.orchestrate_parallel(env.conv_id, [["p1", "p2"]])
    assert result.success
    for response in result.data["responses"]:
        assert response["context"]["messages_sent"] == 1
        assert env.reports.get_by_message(response["message_id"]) is not None


def test_parallel_stream_response_events_carry_context(env):
    with patch("httpx.post", side_effect=lambda *a, **k: _ok()):
        events = list(env.handler.orchestrate_parallel_stream(env.conv_id, [["p1", "p2"]]))
    responses = [e for e in events if e["event"] == "response"]
    assert len(responses) == 2
    assert all(e["context"]["billed_input_tokens"] == 42 for e in responses)


def test_auto_loop_response_events_carry_context(env):
    with patch("httpx.post", side_effect=lambda *a, **k: _ok("fertig @done")):
        events = list(env.handler.auto_loop(env.conv_id, ["p1"], max_rounds=1))
    response = next(e for e in events if e["event"] == "response")
    assert response["context"]["messages_total"] == 1
    assert response["context"]["adapter"] == "universal"


def test_delete_conversation_removes_reports(env):
    with patch("httpx.post", return_value=_ok()):
        env.service.invoke_participant(env.conv_id, "p1")
    env.service.delete_conversation(env.conv_id)
    assert env.reports.list_by_conversation(env.conv_id) == []


def test_export_contains_context_reports(env):
    with patch("httpx.post", side_effect=[_http_error(400), _ok()]):
        with pytest.raises(Exception):
            env.service.invoke_participant(env.conv_id, "p1")
        env.service.invoke_participant(env.conv_id, "p1")
    exported = DataExportService(env.service).export_conversation(env.conv_id)
    assert len(exported["context_reports"]) == 2
    assert {r["message_id"] is None for r in exported["context_reports"]} == {True, False}


# ── API ──────────────────────────────────────────────────────────────────

def test_conversation_messages_include_compact_context(env):
    with patch("httpx.post", return_value=_ok()):
        env.service.invoke_participant(env.conv_id, "p1")
    data = env.client().get(f"/conversations/{env.conv_id}").get_json()
    user_msg, model_msg = data["messages"]
    assert user_msg["context"] is None
    assert model_msg["context"] == {
        "messages_sent": 1, "messages_total": 1, "truncated": False, "omitted_sequences": None,
        "files": 0, "read_results": 0, "skipped_files": 0, "estimated_tokens": model_msg["context"]["estimated_tokens"],
        "billed_input_tokens": 42, "billed_output_tokens": 7, "adapter": "universal", "attempts": 1,
    }


def test_message_context_endpoint_returns_full_report(env):
    with patch("httpx.post", return_value=_ok()):
        env.service.invoke_participant(env.conv_id, "p1")
    message = _model_messages(env)[-1]
    response = env.client().get(f"/conversations/{env.conv_id}/messages/{message.id}/context")
    assert response.status_code == 200
    data = response.get_json()
    assert data["message_id"] == message.id
    assert data["usage"] == {"input_tokens": 42, "output_tokens": 7}
    assert data["report"]["system_parts"] == []
    assert data["report"]["truncation_limit"] == 25


def test_message_context_endpoint_404s(env):
    client = env.client()
    user_message = env.service.load_conversation(env.conv_id).messages[0]
    assert client.get(f"/conversations/nope/messages/{user_message.id}/context").status_code == 404
    assert client.get(f"/conversations/{env.conv_id}/messages/nope/context").status_code == 404
    response = client.get(f"/conversations/{env.conv_id}/messages/{user_message.id}/context")
    assert response.status_code == 404
    assert response.get_json()["type"] == "ContextReportNotFound"


def test_context_preview_does_not_call_provider(env):
    with patch("httpx.post", side_effect=AssertionError("Vorschau darf keinen Provider aufrufen")), \
         patch("httpx.stream", side_effect=AssertionError("Vorschau darf keinen Provider aufrufen")):
        response = env.client().get(f"/conversations/{env.conv_id}/participants/p1/context-preview")
    assert response.status_code == 200
    data = response.get_json()
    assert data["participant_id"] == "p1"
    assert data["report"]["messages_sent"] == 1
    assert env.reports.list_by_conversation(env.conv_id) == []      # Vorschau speichert nichts
    assert env.runs.list_by_conversation(env.conv_id) == []


def test_context_preview_errors(env):
    client = env.client()
    assert client.get("/conversations/nope/participants/p1/context-preview").status_code == 404
    assert client.get(f"/conversations/{env.conv_id}/participants/zz/context-preview").status_code == 404

    class NoPreview:
        provider = "fake"

        def complete(self, conversation, participant):
            return "x"

    env.service._registry.register("p2", NoPreview())
    response = client.get(f"/conversations/{env.conv_id}/participants/p2/context-preview")
    assert response.status_code == 409
    assert response.get_json()["type"] == "PreviewUnavailable"


# ── Migration ────────────────────────────────────────────────────────────

def test_existing_database_migrates_without_data_loss():
    conn = sqlite3.connect(":memory:")
    initialize_schema(conn)
    # Stand vor 007: Tabelle fehlt, Migration nicht eingetragen
    conn.execute("DROP TABLE context_reports")
    conn.execute("DELETE FROM _migrations WHERE id = '007_context_reports'")
    conn.execute("INSERT INTO conversations (id, status, topic, floor, created_at) "
                 "VALUES ('c1', 'open', 'Alt', NULL, '2026-01-01T00:00:00+00:00')")
    conn.commit()

    applied = run_migrations(conn, is_postgres=False)

    assert "007_context_reports" in applied
    assert conn.execute("SELECT topic FROM conversations WHERE id = 'c1'").fetchone() == ("Alt",)
    assert conn.execute("SELECT COUNT(*) FROM context_reports").fetchone() == (0,)
