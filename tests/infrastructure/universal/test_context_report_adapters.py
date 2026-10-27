"""K1: Adapter liefern Kontext-Report und Usage als Rueckgabewert (Completion).

- Der Report entsteht aus der tatsaechlich gesendeten Anfrage (prepare_request).
- ResilientAdapter baut die Anfrage einmal; alle Versuche senden denselben Body.
- Gleichzeitige Aufrufe desselben Adapters vertauschen ihre Usage nicht (A4).
"""

import asyncio
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

import conclave.infrastructure.universal.adapter as universal
from conclave.application.adapter_registry import AdapterRegistry
from conclave.domain.conversation import Conversation
from conclave.domain.message import Message, MessageAuthorType
from conclave.domain.model_response import Completion
from conclave.domain.participant import Participant, ParticipantType
from conclave.infrastructure.sqlite.run_repository import SQLiteRunRepository
from conclave.infrastructure.universal.adapter import UniversalAdapter
from conclave.infrastructure.universal.resilient import ResilientAdapter

API_URL = "https://api.openai.com/v1/chat/completions"
SRC = Path(__file__).resolve().parents[3] / "src" / "conclave"


def _msg(seq, content="x", author=None):
    author_type = MessageAuthorType.MODEL if author else MessageAuthorType.USER
    return Message(id=f"m{seq}", conversation_id="c", author_type=author_type, author_id=author,
                   content=content, sequence=seq, created_at=datetime.now(timezone.utc))


def _conv(messages, rules=""):
    conv = Conversation(id="c", topic="t")
    conv.messages = messages
    conv.rules = rules
    return conv


PART = Participant(id="a", conversation_id="c", participant_type=ParticipantType.MODEL, name="A")


def _ok(text="OK", usage=(10, 2)):
    return httpx.Response(200, json={
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1]},
    }, request=httpx.Request("POST", API_URL))


class _Recorder:
    """Fake fuer httpx.post: zeichnet jede Payload auf."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.bodies = []

    def __call__(self, url, json=None, **kwargs):
        self.bodies.append(json)
        result = self.responses.pop(0)
        return result(json) if callable(result) else result


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "ziel.md").write_text("ZIEL-ALT", encoding="utf-8")
    (ws / "gross.md").write_text("x" * 2000, encoding="utf-8")
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(ws))
    monkeypatch.setenv("CONCLAVE_WORKSPACE_AGENT_READ_LIMIT_BYTES", "1000")
    return ws


def test_executed_body_is_the_prepared_body():
    adapter = UniversalAdapter(api_url=API_URL, api_key="k", model="m", system_prompt="Sei knapp.")
    conv = _conv([_msg(1, "Frage")])
    prepared = adapter.prepare_request(conv, PART)
    recorder = _Recorder([_ok()])
    with patch("httpx.post", recorder):
        result = adapter.complete(conv, PART)
    assert recorder.bodies == [prepared.body]
    assert isinstance(result, Completion)
    assert result.text == "OK"
    assert (result.usage.input_tokens, result.usage.output_tokens) == (10, 2)
    assert result.report == prepared.report


def test_long_conversation_report_matches_truncation(monkeypatch):
    monkeypatch.setattr(universal, "MAX_MESSAGES", 5)
    msgs = [_msg(1, "Aufgabe")] + [_msg(i, f"n{i}", author="b" if i % 2 else None) for i in range(2, 21)]
    report = UniversalAdapter(api_url=API_URL, api_key="k", model="m").prepare_request(_conv(msgs), PART).report
    assert (report.messages_total, report.messages_sent) == (20, 5)
    assert report.anchor_sequence == 1
    assert report.omitted_sequences == (2, 16)
    assert report.truncation_limit == 5
    assert report.adapter == "universal"


def test_report_counts_conclave_messages_not_merged_provider_messages():
    msgs = [_msg(1, "a"), _msg(2, "b"), _msg(3, "c")]          # drei User-Nachrichten in Folge
    prepared = UniversalAdapter(api_url=API_URL, api_key="k", model="m").prepare_request(_conv(msgs), PART)
    provider_messages = [m for m in prepared.body["messages"] if m["role"] != "system"]
    assert len(provider_messages) == 1                         # zusammengefuehrt (A8)
    assert prepared.report.messages_sent == 3


def test_context_files_loaded_and_skipped_are_reported(workspace):
    conv = _conv([_msg(1)], rules="context_files: ziel.md, gross.md, ../weg.md, fehlt.md\nSei nett.")
    report = UniversalAdapter(api_url=API_URL, api_key="k", model="m").prepare_request(conv, PART).report
    assert report.context_files == ({"path": "ziel.md", "bytes": len("ZIEL-ALT")},)
    assert {(s["path"], s["reason"]) for s in report.skipped_context_files} == {
        ("gross.md", "too_large"),
        ("../weg.md", "not_found_or_not_allowed"),
        ("fehlt.md", "not_found_or_not_allowed"),
    }
    assert report.system_parts == ("context_files", "rules", "workspace_info")


def test_workspace_info_only_when_workspace_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(tmp_path / "gibt-es-nicht"))
    adapter = UniversalAdapter(api_url=API_URL, api_key="k", model="m", system_prompt="P")
    assert adapter.prepare_request(_conv([_msg(1)]), PART).report.system_parts == ("agent_prompt",)
    (tmp_path / "gibt-es-nicht").mkdir()
    assert adapter.prepare_request(_conv([_msg(1)]), PART).report.system_parts == ("agent_prompt", "workspace_info")


def test_inline_files_and_read_results_in_sent_history():
    msgs = [
        _msg(1, "Lies das:\n--- Datei: notiz.md ---\n```\nInhalt\n```\n"),
        _msg(2, "[tool_event:t]\n\n--- Datei: code.py ---\n```\nx = 1\n```\n", author="a"),
    ]
    report = UniversalAdapter(api_url=API_URL, api_key="k", model="m").prepare_request(_conv(msgs), PART).report
    assert [f["path"] for f in report.inline_files] == ["notiz.md"]
    assert [f["path"] for f in report.read_results] == ["code.py"]


def test_resilient_adapter_builds_request_once_and_counts_attempts(workspace):
    conv = _conv([_msg(1)], rules="context_files: ziel.md")

    def fail_and_change_file(body):
        # Zwischen den Versuchen aendert sich die Datei - gesendet wird trotzdem der erste Stand
        (workspace / "ziel.md").write_text("ZIEL-NEU", encoding="utf-8")
        return httpx.Response(503, json={"error": "busy"}, request=httpx.Request("POST", API_URL))

    recorder = _Recorder([fail_and_change_file, _ok()])
    adapter = ResilientAdapter(UniversalAdapter(api_url=API_URL, api_key="k", model="m"), sleep_fn=lambda s: None)
    with patch("httpx.post", recorder):
        result = adapter.complete(conv, PART)
    assert len(recorder.bodies) == 2
    assert recorder.bodies[0] == recorder.bodies[1]
    assert "ZIEL-ALT" in json.dumps(recorder.bodies[1])
    assert result.report.attempts == 2


def test_resilient_adapter_single_attempt_keeps_report():
    recorder = _Recorder([_ok()])
    adapter = ResilientAdapter(UniversalAdapter(api_url=API_URL, api_key="k", model="m"))
    with patch("httpx.post", recorder):
        result = adapter.complete(_conv([_msg(1)]), PART)
    assert result.report.attempts == 1


def test_concurrent_calls_of_same_adapter_keep_their_own_usage():
    """A4: frueher las conversation_flow adapter.last_usage - zwei parallele Aufrufe konnten tauschen."""
    adapter = UniversalAdapter(api_url=API_URL, api_key="k", model="m")
    barrier = threading.Barrier(2)

    def respond(body):
        barrier.wait(timeout=5)          # beide Anfragen sind gleichzeitig unterwegs
        question = body["messages"][-1]["content"]
        return _ok(text=question, usage=(len(question), 1))

    results = {}

    def call(question):
        results[question] = adapter.complete(_conv([_msg(1, question)]), PART)

    with patch("httpx.post", lambda url, json=None, **kw: respond(json)):
        threads = [threading.Thread(target=call, args=(q,)) for q in ("kurz", "deutlich laenger")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
    assert results["kurz"].usage.input_tokens == len("kurz")
    assert results["deutlich laenger"].usage.input_tokens == len("deutlich laenger")


def test_parallel_flow_records_each_run_with_its_own_usage(service, db_connection):
    adapter = UniversalAdapter(api_url=API_URL, api_key="k", model="m")
    registry = AdapterRegistry()
    registry.register("p1", adapter)
    service.set_adapter_registry(registry)
    run_repo = SQLiteRunRepository(db_connection)
    service.set_run_repository(run_repo)
    conv = service.create_conversation()
    service.register_participant(conversation_id=conv.id, participant_id="p1",
                                 participant_type=ParticipantType.MODEL, name="GPT")
    service.add_user_message(conv.id, "Frage")
    barrier = threading.Barrier(2)
    counter = iter([111, 222])
    lock = threading.Lock()

    def respond(url, json=None, **kw):
        with lock:
            tokens = next(counter)
        barrier.wait(timeout=5)
        return _ok(text=str(tokens), usage=(tokens, 1))

    async def both():
        return await asyncio.gather(
            service.async_complete_participant(conv.id, "p1"),
            service.async_complete_participant(conv.id, "p1"),
        )

    with patch("httpx.post", respond):
        texts = asyncio.run(both())
    runs = run_repo.list_by_conversation(conv.id)
    assert sorted(texts) == ["111", "222"]
    assert sorted(r.usage.input_tokens for r in runs) == [111, 222]


def test_native_anthropic_adapter_sends_full_history_and_reports_it():
    from conclave.infrastructure.anthropic.adapter import AnthropicAdapter
    adapter = AnthropicAdapter(api_key="k", system_prompt="P")
    response = MagicMock()
    response.content = [MagicMock(text="Antwort")]
    response.usage.input_tokens, response.usage.output_tokens = 40, 3
    adapter._client = MagicMock()
    adapter._client.messages.create.return_value = response
    msgs = [_msg(i) for i in range(1, 41)]
    result = adapter.complete(_conv(msgs, rules="context_files: ziel.md\nSei nett."), PART)
    assert result.text == "Antwort"
    assert (result.usage.input_tokens, result.usage.output_tokens) == (40, 3)
    report = result.report
    assert report.adapter == "anthropic-native"
    assert (report.messages_total, report.messages_sent) == (40, 40)
    assert report.truncation_limit is None
    assert report.system_parts == ("agent_prompt", "rules")
    assert report.skipped_context_files == ({"path": "ziel.md", "reason": "adapter_unsupported"},)


def test_native_openai_stream_ends_with_completion():
    from conclave.infrastructure.openai.adapter import OpenAIAdapter
    adapter = OpenAIAdapter(api_key="k")
    delta = MagicMock(type="response.output_text.delta", delta="Hi")
    done = MagicMock(type="response.completed")
    done.response.usage.input_tokens, done.response.usage.output_tokens = 7, 1
    adapter._client = MagicMock()
    adapter._client.responses.create.return_value = iter([delta, done])
    chunks = list(adapter.stream(_conv([_msg(1)]), PART))
    assert chunks[0] == "Hi"
    assert isinstance(chunks[-1], Completion)
    assert (chunks[-1].usage.input_tokens, chunks[-1].report.adapter) == (7, "openai-native")


def test_no_last_usage_in_call_path():
    """Abnahme K1: Usage nur noch als Rueckgabewert, kein Adapter-Zustand."""
    offenders = [str(p.relative_to(SRC)) for p in SRC.rglob("*.py") if "last_usage" in p.read_text(encoding="utf-8")]
    assert offenders == []
