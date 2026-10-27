"""K5: Kuerzungslimit pro Agent (max_messages).

None = globaler Default (nur Preset-Agenten kuerzen), 0 = keine Kuerzung,
sonst hoechstens so viele Nachrichten - fuer Universal- und native Adapter.
Bearbeiten ohne Angabe behaelt den gespeicherten Wert (vgl. Key-Fehler v0.2.0).
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

import conclave.infrastructure.universal.adapter as universal
from conclave.domain.agent import Agent
from conclave.domain.context_report import select_messages
from conclave.domain.conversation import Conversation
from conclave.domain.message import Message, MessageAuthorType
from conclave.domain.participant import Participant, ParticipantType
from conclave.infrastructure.sqlite.agent_repository import SQLiteAgentRepository

API_URL = "https://api.openai.com/v1/chat/completions"
PART = Participant(id="a", conversation_id="c", participant_type=ParticipantType.MODEL, name="A")


def _msg(seq, author=None):
    return Message(id=f"m{seq}", conversation_id="c",
                   author_type=MessageAuthorType.MODEL if author else MessageAuthorType.USER,
                   author_id=author, content=f"n{seq}", sequence=seq, created_at=datetime.now(timezone.utc))


def _conv(n=20):
    conv = Conversation(id="c", topic="t")
    conv.messages = [_msg(1)] + [_msg(i, author="b" if i % 2 else None) for i in range(2, n + 1)]
    return conv


# ── Domain ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", [None, 0, 1, 40])
def test_agent_accepts_empty_zero_and_positive_limits(value):
    assert Agent(id="a", name="A", provider="openai", model="m", max_messages=value).max_messages == value


@pytest.mark.parametrize("value", [-1, True, "5", 2.5])
def test_agent_rejects_invalid_limits(value):
    with pytest.raises(ValueError):
        Agent(id="a", name="A", provider="openai", model="m", max_messages=value)


def test_select_messages_keeps_anchor_and_handles_edge_limits():
    msgs = _conv(10).messages
    assert select_messages(msgs, None) == msgs
    assert select_messages(msgs, 0) == msgs
    assert [m.sequence for m in select_messages(msgs, 4)] == [1, 8, 9, 10]
    assert [m.sequence for m in select_messages(msgs, 1)] == [10]


# ── Adapter ──────────────────────────────────────────────────────────────

def test_universal_adapter_uses_agent_limit(monkeypatch):
    monkeypatch.setattr(universal, "MAX_MESSAGES", 25)
    adapter = universal.UniversalAdapter(api_url=API_URL, api_key="k", model="m", max_messages=5)
    report = adapter.prepare_request(_conv(20), PART).report
    assert (report.messages_sent, report.truncation_limit, report.anchor_sequence) == (5, 5, 1)


def test_universal_adapter_zero_means_no_truncation(monkeypatch):
    monkeypatch.setattr(universal, "MAX_MESSAGES", 5)
    adapter = universal.UniversalAdapter(api_url=API_URL, api_key="k", model="m", max_messages=0)
    report = adapter.prepare_request(_conv(20), PART).report
    assert (report.messages_sent, report.truncation_limit) == (20, None)


def test_universal_adapter_empty_uses_global_default(monkeypatch):
    monkeypatch.setattr(universal, "MAX_MESSAGES", 7)
    report = universal.UniversalAdapter(api_url=API_URL, api_key="k", model="m").prepare_request(_conv(20), PART).report
    assert (report.messages_sent, report.truncation_limit) == (7, 7)


def _anthropic(max_messages):
    from conclave.infrastructure.anthropic.adapter import AnthropicAdapter
    adapter = AnthropicAdapter(api_key="k", max_messages=max_messages)
    response = MagicMock()
    response.content = [MagicMock(text="ok")]
    response.usage.input_tokens, response.usage.output_tokens = 1, 1
    adapter._client = MagicMock()
    adapter._client.messages.create.return_value = response
    return adapter


def test_native_adapter_without_limit_sends_full_history():
    adapter = _anthropic(None)
    result = adapter.complete(_conv(30), PART)
    assert len(adapter._client.messages.create.call_args.kwargs["messages"]) == 30
    assert (result.report.messages_sent, result.report.truncation_limit) == (30, None)


def test_native_adapter_with_limit_truncates_like_universal():
    adapter = _anthropic(6)
    result = adapter.complete(_conv(30), PART)
    sent = adapter._client.messages.create.call_args.kwargs["messages"]
    assert len(sent) == 6 and sent[0]["content"] == "n1"         # Anker bleibt
    assert (result.report.messages_sent, result.report.truncation_limit) == (6, 6)
    assert adapter.context_report(_conv(30), PART).messages_sent == 6   # Vorschau gleich


def test_native_openai_stream_respects_limit():
    from conclave.infrastructure.openai.adapter import OpenAIAdapter
    adapter = OpenAIAdapter(api_key="k", max_messages=3)
    adapter._client = MagicMock()
    adapter._client.responses.create.return_value = iter([])
    chunks = list(adapter.stream(_conv(10), PART))
    assert len(adapter._client.responses.create.call_args.kwargs["input"]) == 3
    assert chunks[-1].report.messages_sent == 3


def test_bootstrap_passes_limit_to_both_adapter_kinds():
    from conclave.cli.bootstrap import _make_adapter
    preset_agent = Agent(id="p", name="P", provider="openai", model="gpt", preset="openai", max_messages=9)
    native_agent = Agent(id="n", name="N", provider="anthropic", model="claude", max_messages=4)
    assert _make_adapter(preset_agent, api_key="k")._max_messages == 9
    assert _make_adapter(native_agent, api_key="k")._max_messages == 4


# ── Speicherung ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", [None, 0, 12])
def test_sqlite_repository_roundtrip(db_connection, crypto, value):
    repo = SQLiteAgentRepository(db_connection, crypto)
    repo.save(Agent(id="a", name="A", provider="openai", model="m", max_messages=value))
    assert repo.get("a").max_messages == value
    assert repo.list_all()[0].max_messages == value


# ── API ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client(db_connection, crypto, service):
    pytest.importorskip("flask")
    from conclave.api.app import create_app
    from conclave.application.agent_service import AgentService
    from conclave.cli.handler import CLIHandler
    agents = AgentService(SQLiteAgentRepository(db_connection, crypto))
    app = create_app(CLIHandler(service, agent_service=agents), agent_service=agents)
    app.config["TESTING"] = True
    c = app.test_client()
    c.agents = agents
    return c


BASE = {"name": "GPT", "provider": "openai", "model": "gpt", "preset": "openai"}


def test_api_create_edit_keep_and_reset(client):
    assert client.post("/agents", json={"id": "g", **BASE, "max_messages": 10}).status_code == 201
    assert client.get("/agents/g").get_json()["max_messages"] == 10

    assert client.put("/agents/g", json={**BASE, "topic": "neu"}).status_code == 200
    assert client.agents.get_agent("g").max_messages == 10          # ohne Angabe behalten

    client.put("/agents/g", json={**BASE, "max_messages": 0})
    assert client.agents.get_agent("g").max_messages == 0

    client.put("/agents/g", json={**BASE, "max_messages": None})
    assert client.agents.get_agent("g").max_messages is None        # null = Default


@pytest.mark.parametrize("value", [-1, "zehn", True, 1.5])
def test_api_rejects_invalid_limits(client, value):
    assert client.post("/agents", json={"id": "g", **BASE, "max_messages": value}).status_code == 400
    client.post("/agents", json={"id": "h", **BASE})
    assert client.put("/agents/h", json={**BASE, "max_messages": value}).status_code == 400


# ── CLI ──────────────────────────────────────────────────────────────────

def _cli(handler, argv):
    from conclave.cli.main import run
    with patch.multiple("conclave.cli.main",
                        build_service=MagicMock(return_value=MagicMock()),
                        build_agent_service=MagicMock(return_value=MagicMock()),
                        build_registry=MagicMock(return_value=None),
                        CLIHandler=MagicMock(return_value=handler)):
        return run(argv)


def _handler(stored):
    from conclave.cli.handler import CLIResult
    handler = MagicMock()
    handler.get_agent.return_value = CLIResult(success=True, message="ok", data={
        "id": "a1", "created_at": "2026-01-01T00:00:00+00:00", "max_messages": stored})
    handler.update_agent.return_value = CLIResult(success=True, message="ok", data={"id": "a1"})
    handler.create_agent.return_value = CLIResult(success=True, message="ok", data={"id": "a1"})
    return handler


@pytest.mark.parametrize("args, expected", [
    ([], 8),                                   # weglassen = behalten
    (["--max-messages", "default"], None),     # zurueck auf Default
    (["--max-messages", "0"], 0),
    (["--max-messages", "15"], 15),
])
def test_cli_agent_edit_keeps_or_changes_limit(args, expected):
    handler = _handler(stored=8)
    assert _cli(handler, ["agent-edit", "a1", "--name", "A", "--model", "m", *args]) == 0
    assert handler.update_agent.call_args.args[0].max_messages == expected


def test_cli_agent_new_sets_limit():
    handler = _handler(stored=None)
    assert _cli(handler, ["agent-new", "a1", "--name", "A", "--model", "m", "--max-messages", "5"]) == 0
    assert handler.create_agent.call_args.args[0].max_messages == 5


def test_agent_form_has_limit_field():
    from pathlib import Path
    assets = Path(__file__).resolve().parents[2] / "src" / "conclave" / "assets"
    html = (assets / "conclave-ui.html").read_text(encoding="utf-8")
    js = (assets / "static" / "js" / "features" / "agents.js").read_text(encoding="utf-8")
    assert 'id="aMaxMessages"' in html
    assert "max_messages" in js and "aMaxMessages" in js
