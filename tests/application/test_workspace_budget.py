"""R6 (conclave#41): Grenzen fuer @workspace und @read, @read nur nach Freigabe, Tool-Events.

- @workspace wird nur in Nachrichten von Mensch und Agent eingesetzt, je Datei einmal,
  hoechstens 10 Dateien und hoechstens agent_read_limit pro Nachricht, in einem Durchlauf
  (eingesetzter Text wird nicht erneut durchsucht).
- @read in Modellantworten ist ohne Freigabe der Conversation aus.
"""

from datetime import UTC, datetime

import pytest

from conclave.application.conversation_flow import ConversationFlowService
from conclave.cli.bootstrap import build_service
from conclave.cli.config import ConclaveConfig
from conclave.domain.conversation import Conversation
from conclave.domain.message import Message, MessageAuthorType
from conclave.domain.participant import ParticipantType


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "a.md").write_text("AAA", encoding="utf-8")
    (ws / "rekursiv.md").write_text("@workspace/a.md @workspace/a.md @workspace/rekursiv.md", encoding="utf-8")
    for i in range(12):
        (ws / f"f{i}.md").write_text(f"F{i}", encoding="utf-8")
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(ws))
    return ws


def _conv(*messages):
    conv = Conversation.create()
    conv.messages = list(messages)
    return conv


def _msg(content, author=MessageAuthorType.USER, n=1):
    return Message(id=f"m{n}", conversation_id="c", author_type=author, author_id=None if author ==
                   MessageAuthorType.USER else "p1", content=content, sequence=n, created_at=datetime.now(UTC))


def _expanded(conv):
    return ConversationFlowService._expand_workspace_refs(conv).messages


def test_identical_references_are_expanded_once(workspace):
    [msg] = _expanded(_conv(_msg(" ".join(["@workspace/a.md"] * 200))))
    assert msg.content.count("AAA") == 1
    assert len(msg.content) < 10_000


def test_inserted_content_is_not_scanned_again(workspace):
    [msg] = _expanded(_conv(_msg("@workspace/rekursiv.md")))
    assert msg.content.count("AAA") == 0                                     # nur der Text der Datei
    assert "@workspace/a.md @workspace/a.md" in msg.content


def test_at_most_ten_files_per_message(workspace):
    refs = " ".join(f"@workspace/f{i}.md" for i in range(12))
    [msg] = _expanded(_conv(_msg(refs)))
    assert sum(f"F{i}" in msg.content for i in range(12)) == 10
    assert "hoechstens 10" in msg.content


def test_total_size_per_message_is_limited(workspace, monkeypatch):
    monkeypatch.setenv("CONCLAVE_WORKSPACE_AGENT_READ_LIMIT_BYTES", "5")
    [msg] = _expanded(_conv(_msg("@workspace/f1.md @workspace/f2.md @workspace/f3.md")))
    assert "F1" in msg.content and "F2" in msg.content                     # 2 + 2 Bytes
    assert "F3" not in msg.content and "Gesamtgroesse" in msg.content


def test_model_messages_are_not_expanded(workspace):
    user, model = _expanded(_conv(_msg("@workspace/a.md"), _msg("@workspace/a.md", MessageAuthorType.MODEL, 2)))
    assert "AAA" in user.content
    assert model.content == "@workspace/a.md"


# ── Ueber den Dienst: Tool-Events, @read nur mit Freigabe ─────────────────

class _Answer:
    provider = "fake"

    def __init__(self, text):
        self.text = text

    def complete(self, conversation, participant):
        return self.text


@pytest.fixture
def service(tmp_path, workspace):
    svc = build_service(config=ConclaveConfig(db_path=tmp_path / "c.db"))
    conv = svc.create_conversation()
    svc.register_participant(conversation_id=conv.id, participant_id="m", participant_type=ParticipantType.MODEL,
                             name="M")
    return svc, conv.id


def test_user_message_records_expansions_as_tool_events(service):
    svc, cid = service
    conv = svc.add_user_message(cid, "@workspace/a.md und @workspace/a.md und @workspace/fehlt.md", origin="human")
    events = svc.list_tool_events_by_message(conv.messages[-1].id)
    summary = sorted((e.tool, e.status, e.output_json.get("path") or e.input_json.get("path")) for e in events)
    assert summary == [("workspace.expand", "failed", "fehlt.md"), ("workspace.expand", "succeeded", "a.md")]
    ok = next(e for e in events if e.status == "succeeded")
    assert ok.output_json["bytes"] == 3


def test_read_in_model_answer_is_off_by_default(service):
    svc, cid = service
    svc.add_user_message(cid, "Hallo")
    conv = svc.invoke_participant(conversation_id=cid, participant_id="m", adapter=_Answer("@read(a.md)"))
    message = conv.messages[-1]
    assert "AAA" not in message.content and "nicht erlaubt" in message.content
    [event] = svc.list_tool_events_by_message(message.id)
    assert (event.tool, event.status, event.error) == ("workspace.read", "failed", "read_not_allowed")


def test_read_works_after_opt_in_and_is_limited(service):
    svc, cid = service
    svc.set_model_read(cid, True)
    svc.add_user_message(cid, "Hallo")
    answer = " ".join(["@read(a.md)"] * 50 + [f"@read(f{i}.md)" for i in range(12)])
    conv = svc.invoke_participant(conversation_id=cid, participant_id="m", adapter=_Answer(answer))
    message = conv.messages[-1]
    assert message.content.count("AAA") == 1
    assert sum(f"F{i}\n" in message.content for i in range(12)) == 9      # a.md + 9 weitere = 10
    assert svc.load_conversation(cid).model_read is True
