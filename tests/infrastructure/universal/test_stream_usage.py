"""v0.2.2: Streaming von Preset-Agenten - Token-Angaben (A7) und Stream-Formate.

Bis v0.2.1 setzte UniversalAdapter.stream() die Usage weder neu noch zurueck;
conversation_flow las sie nach dem Stream trotzdem aus. Gestreamte Aufrufe
speicherten so die Token-Zahlen des vorherigen complete()-Aufrufs oder keine.
"""

import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from conclave.application.adapter_registry import AdapterRegistry
from conclave.domain.model_response import Completion
from conclave.domain.participant import ParticipantType
from conclave.infrastructure.sqlite.run_repository import SQLiteRunRepository
from conclave.infrastructure.universal.adapter import UniversalAdapter

API_URL = "https://api.openai.com/v1/chat/completions"


class _Response:
    def __init__(self, data):
        self._data = data
        self.status_code = 200
        self.text = json.dumps(data)

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def _completion(text="Antwort", usage=(11, 22)):
    data = {"choices": [{"message": {"content": text}}]}
    if usage:
        data["usage"] = {"prompt_tokens": usage[0], "completion_tokens": usage[1]}
    return _Response(data)


def _sse(chunks):
    return [f"data: {json.dumps(c)}" for c in chunks] + ["data: [DONE]"]


def _delta(text):
    return {"choices": [{"delta": {"content": text}}], "usage": None}


class _StreamRecorder:
    """Ersetzt httpx.stream, zeichnet den gesendeten Body auf."""

    def __init__(self, lines):
        self.lines = lines
        self.bodies = []
        self.urls = []
        self.params = []

    @contextmanager
    def __call__(self, method, url, json=None, params=None, **kwargs):
        self.bodies.append(json)
        self.urls.append(url)
        self.params.append(params or {})
        recorder = self

        class _Resp:
            def raise_for_status(self):
                pass

            def iter_lines(self):
                yield from recorder.lines

        yield _Resp()


def _adapter(stream_usage=False):
    return UniversalAdapter(api_url=API_URL, api_key="sk-test", model="gpt-test",
                            provider_name="openai", stream_usage=stream_usage)


@pytest.fixture
def conversation_with_agent(service, db_connection):
    """Service mit Run-Repository und einem Preset-Agenten (UniversalAdapter) als p1."""
    adapter = _adapter(stream_usage=True)
    registry = AdapterRegistry()
    registry.register("p1", adapter)
    service.set_adapter_registry(registry)
    run_repo = SQLiteRunRepository(db_connection)
    service.set_run_repository(run_repo)
    conv = service.create_conversation()
    service.register_participant(conversation_id=conv.id, participant_id="p1",
                                 participant_type=ParticipantType.MODEL, name="GPT")
    service.add_user_message(conv.id, "Frage")
    return service, conv, adapter, run_repo


def _stream_text(service, conv_id):
    return "".join(service.stream_participant(conv_id, "p1"))


def test_stream_after_complete_does_not_reuse_old_usage(conversation_with_agent):
    service, conv, adapter, run_repo = conversation_with_agent
    with patch("httpx.post", return_value=_completion(usage=(11, 22))):
        service.invoke_participant(conversation_id=conv.id, participant_id="p1")
    invoke_run = next(r for r in run_repo.list_by_conversation(conv.id) if r.kind == "invoke")
    assert invoke_run.usage.input_tokens == 11

    service.add_user_message(conv.id, "Noch eine Frage")
    with patch("httpx.stream", _StreamRecorder(_sse([_delta("Hal"), _delta("lo")]))):
        assert _stream_text(service, conv.id) == "Hallo"

    assert not hasattr(adapter, "last_usage")
    stream_run = next(r for r in run_repo.list_by_conversation(conv.id) if r.kind == "stream")
    assert stream_run.status == "succeeded"
    assert stream_run.usage is None or stream_run.usage.input_tokens is None


def test_stream_with_usage_in_last_chunk_stores_real_tokens(conversation_with_agent):
    service, conv, adapter, run_repo = conversation_with_agent
    final = {"choices": [], "usage": {"prompt_tokens": 120, "completion_tokens": 7}}
    with patch("httpx.stream", _StreamRecorder(_sse([_delta("Ja"), final]))):
        assert _stream_text(service, conv.id) == "Ja"

    stream_run = next(r for r in run_repo.list_by_conversation(conv.id) if r.kind == "stream")
    assert stream_run.usage.input_tokens == 120
    assert stream_run.usage.output_tokens == 7


def test_stream_options_only_for_providers_that_support_them(conversation_with_agent):
    from conclave.domain.conversation import Conversation
    from conclave.domain.participant import Participant

    conv = Conversation(id="c", topic="t")
    part = Participant(id="p1", conversation_id="c", participant_type=ParticipantType.MODEL, name="GPT")

    with_usage, without_usage = _StreamRecorder(_sse([_delta("x")])), _StreamRecorder(_sse([_delta("x")]))
    with patch("httpx.stream", with_usage):
        list(_adapter(stream_usage=True).stream(conv, part))
    with patch("httpx.stream", without_usage):
        list(_adapter(stream_usage=False).stream(conv, part))

    assert with_usage.bodies[0]["stream_options"] == {"include_usage": True}
    assert "stream_options" not in without_usage.bodies[0]


def test_presets_enable_stream_usage_only_where_supported():
    from conclave.infrastructure.universal.presets import PRESETS
    enabled = {name for name, preset in PRESETS.items() if preset.get("stream_usage")}
    assert enabled == {"openai", "openai-no-thinking", "qwen-dashscope", "qwen-dashscope-thinking", "deepseek"}


def test_adapter_factory_passes_stream_usage_from_preset():
    from conclave.cli.bootstrap import _make_universal_adapter
    from conclave.domain.agent import Agent

    def build(preset):
        agent = Agent(id="a", name="A", provider=preset, model="m", preset=preset, api_key="k")
        return _make_universal_adapter(agent, "k")

    assert build("deepseek")._stream_usage is True
    assert build("mistral")._stream_usage is False



# ── Stream-Formate je Provider (v0.2.2) ───────────────────────────────────

def _preset_adapter(preset, model="m"):
    from conclave.cli.bootstrap import _make_universal_adapter
    from conclave.domain.agent import Agent
    return _make_universal_adapter(Agent(id="a", name="A", provider=preset, model=model, preset=preset, api_key="k"), "k")


def _run_stream(adapter, lines):
    from conclave.domain.conversation import Conversation
    from conclave.domain.participant import Participant
    conv = Conversation(id="c", topic="t")
    part = Participant(id="a", conversation_id="c", participant_type=ParticipantType.MODEL, name="A")
    recorder = _StreamRecorder(lines)
    with patch("httpx.stream", recorder):
        chunks = list(adapter.stream(conv, part))
    final = chunks[-1]
    assert isinstance(final, Completion) and final.text == ""
    text = "".join(c for c in chunks if isinstance(c, str))
    usage = final.usage
    return text, (usage.input_tokens, usage.output_tokens) if usage else None, recorder


def _ev(name, data):
    return [f"event: {name}", f"data: {json.dumps(data)}", ""]


def test_anthropic_stream_yields_text_and_usage():
    lines = (
        _ev("message_start", {"type": "message_start", "message": {"id": "m1", "usage": {"input_tokens": 25, "output_tokens": 1}}})
        + _ev("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
        + _ev("ping", {"type": "ping"})
        + _ev("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hallo"}})
        + _ev("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": " Welt"}})
        + _ev("content_block_stop", {"type": "content_block_stop", "index": 0})
        + _ev("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 15}})
        + _ev("message_stop", {"type": "message_stop"})
    )
    text, usage, rec = _run_stream(_preset_adapter("anthropic"), lines)
    assert text == "Hallo Welt"
    assert usage == (25, 15)
    assert rec.bodies[0]["stream"] is True
    assert "stream_options" not in rec.bodies[0]


def test_gemini_stream_uses_sse_endpoint_and_yields_text_and_usage():
    lines = [
        "data: " + json.dumps({"candidates": [{"content": {"parts": [{"text": "Guten "}], "role": "model"}}]}),
        "",
        "data: " + json.dumps({"candidates": [{"content": {"parts": [{"text": "Tag"}], "role": "model"}, "finishReason": "STOP"}],
                               "usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": 4, "totalTokenCount": 13}}),
    ]
    text, usage, rec = _run_stream(_preset_adapter("gemini", model="gemini-test"), lines)
    assert text == "Guten Tag"
    assert usage == (9, 4)
    assert rec.urls[0].endswith("/models/gemini-test:streamGenerateContent")
    assert rec.params[0]["alt"] == "sse"
    assert "stream" not in rec.bodies[0]


def test_openai_responses_stream_yields_text_and_usage():
    lines = (
        _ev("response.created", {"type": "response.created", "response": {"id": "r1"}})
        + _ev("response.output_text.delta", {"type": "response.output_text.delta", "delta": "Hi"})
        + _ev("response.output_text.delta", {"type": "response.output_text.delta", "delta": " there"})
        + _ev("response.output_text.done", {"type": "response.output_text.done", "text": "Hi there"})
        + _ev("response.completed", {"type": "response.completed",
                                     "response": {"usage": {"input_tokens": 30, "output_tokens": 2}}})
    )
    text, usage, rec = _run_stream(_preset_adapter("openai-responses"), lines)
    assert text == "Hi there"
    assert usage == (30, 2)
    assert rec.bodies[0]["stream"] is True


def test_ollama_ndjson_stream_yields_text_and_usage():
    lines = [
        json.dumps({"model": "llama3.3", "message": {"role": "assistant", "content": "Lo"}, "done": False}),
        json.dumps({"model": "llama3.3", "message": {"role": "assistant", "content": "kal"}, "done": False}),
        json.dumps({"model": "llama3.3", "message": {"role": "assistant", "content": ""}, "done": True,
                    "prompt_eval_count": 5, "eval_count": 3}),
    ]
    adapter = UniversalAdapter(api_url="http://localhost:11434/api/chat", model="llama3.3", provider_name="ollama",
                               auth_format="none", response_path="message.content", usage_path="",
                               usage_input_key="prompt_eval_count", usage_output_key="eval_count")
    text, usage, _ = _run_stream(adapter, lines)
    assert text == "Lokal"
    assert usage == (5, 3)


def test_openai_chat_stream_ignores_null_usage_until_last_chunk():
    lines = _sse([_delta("A"), _delta("B"), {"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 2}}])
    text, usage, rec = _run_stream(_preset_adapter("openai"), lines)
    assert text == "AB"
    assert usage == (3, 2)
    assert rec.bodies[0]["stream_options"] == {"include_usage": True}


def test_claude_preset_stream_persists_answer_end_to_end(service, db_connection):
    """Vorher kam beim Stream eines Claude-Preset-Agenten leerer Text an."""
    registry = AdapterRegistry()
    registry.register("claude", _preset_adapter("anthropic"))
    service.set_adapter_registry(registry)
    run_repo = SQLiteRunRepository(db_connection)
    service.set_run_repository(run_repo)
    conv = service.create_conversation()
    service.register_participant(conversation_id=conv.id, participant_id="claude",
                                 participant_type=ParticipantType.MODEL, name="Claude")
    service.add_user_message(conv.id, "Frage")
    lines = (
        _ev("message_start", {"type": "message_start", "message": {"usage": {"input_tokens": 12, "output_tokens": 1}}})
        + _ev("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Antwort"}})
        + _ev("message_delta", {"type": "message_delta", "usage": {"output_tokens": 6}})
    )
    with patch("httpx.stream", _StreamRecorder(lines)):
        streamed = "".join(service.stream_participant(conv.id, "claude"))
    assert streamed == "Antwort"
    saved = service.load_conversation(conv.id).messages[-1]
    assert saved.content == "Antwort"
    run = next(r for r in run_repo.list_by_conversation(conv.id) if r.kind == "stream")
    assert (run.usage.input_tokens, run.usage.output_tokens) == (12, 6)
