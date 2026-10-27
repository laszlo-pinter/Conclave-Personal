"""v0.2.2 / A7: Token-Angaben gestreamter Aufrufe von Preset-Agenten.

Bis v0.2.1 setzte UniversalAdapter.stream() die Usage weder neu noch zurueck;
conversation_flow las sie nach dem Stream trotzdem aus. Gestreamte Aufrufe
speicherten so die Token-Zahlen des vorherigen complete()-Aufrufs oder keine.
"""

import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from conclave.application.adapter_registry import AdapterRegistry
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

    @contextmanager
    def __call__(self, method, url, json=None, **kwargs):
        self.bodies.append(json)
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
    assert adapter.last_usage.input_tokens == 11

    service.add_user_message(conv.id, "Noch eine Frage")
    with patch("httpx.stream", _StreamRecorder(_sse([_delta("Hal"), _delta("lo")]))):
        assert _stream_text(service, conv.id) == "Hallo"

    assert adapter.last_usage is None
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
