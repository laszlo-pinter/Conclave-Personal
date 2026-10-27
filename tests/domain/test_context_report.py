"""K1: ContextReport als reine Funktion aus den gesendeten Nachrichten."""

from datetime import datetime, timezone

from conclave.domain.context_report import (
    build_context_report,
    estimate_tokens,
    requested_context_files,
)
from conclave.domain.message import Message, MessageAuthorType


def _msg(seq, content="x", author=None):
    author_type = MessageAuthorType.MODEL if author else MessageAuthorType.USER
    return Message(id=f"m{seq}", conversation_id="c", author_type=author_type, author_id=author,
                   content=content, sequence=seq, created_at=datetime.now(timezone.utc))


def test_untruncated_conversation_reports_everything_sent():
    msgs = [_msg(1), _msg(2, author="a"), _msg(3)]
    report = build_context_report(all_messages=msgs, sent_messages=msgs, adapter="universal",
                                  truncation_limit=25)
    assert (report.messages_total, report.messages_sent) == (3, 3)
    assert report.omitted_sequences is None
    assert report.anchor_sequence is None
    assert report.truncated is False
    assert report.truncation_limit == 25


def test_truncated_conversation_reports_omitted_range_and_anchor():
    msgs = [_msg(i) for i in range(1, 11)]
    sent = [msgs[0]] + msgs[-4:]           # Anker + letzte 4
    report = build_context_report(all_messages=msgs, sent_messages=sent, adapter="universal",
                                  truncation_limit=5)
    assert (report.messages_total, report.messages_sent) == (10, 5)
    assert report.omitted_sequences == (2, 6)
    assert report.anchor_sequence == 1
    assert report.truncated is True


def test_truncation_without_anchor():
    msgs = [_msg(i) for i in range(1, 6)]
    report = build_context_report(all_messages=msgs, sent_messages=msgs[-2:], adapter="universal")
    assert report.omitted_sequences == (1, 3)
    assert report.anchor_sequence is None


def test_inline_files_and_read_results_are_told_apart_by_author():
    user = _msg(1, "Bitte pruefen:\n--- Datei: docs/a.md ---\n```\nHallo\n```\n")
    agent = _msg(2, "[tool_event:x]\n\n--- Datei: src/b.py ---\n```\nprint(1)\n```\n", author="a")
    report = build_context_report(all_messages=[user, agent], sent_messages=[user, agent],
                                  adapter="universal")
    assert report.inline_files == ({"path": "docs/a.md", "bytes": 5, "message_seq": 1},)
    assert report.read_results == ({"path": "src/b.py", "bytes": 8, "message_seq": 2},)


def test_omitted_messages_do_not_count_their_files():
    old = _msg(1, "--- Datei: alt.md ---\n```\nALT\n```\n")
    new = _msg(2, "neu")
    report = build_context_report(all_messages=[old, new], sent_messages=[new], adapter="universal")
    assert report.inline_files == ()


def test_estimated_tokens_cover_system_and_sent_messages():
    msgs = [_msg(1, "a" * 70)]
    report = build_context_report(all_messages=msgs, sent_messages=msgs, adapter="universal",
                                  system_text="b" * 35)
    assert report.estimated_tokens == estimate_tokens("a" * 70, "b" * 35) == 30


def test_requested_context_files_parses_rule_lines():
    rules = "Sei knapp.\ncontext_files: a.md, docs/b.md ,\nCONTEXT_FILES: c.md"
    assert requested_context_files(rules) == ["a.md", "docs/b.md", "c.md"]


def test_to_dict_is_json_friendly():
    import json
    msgs = [_msg(i) for i in range(1, 4)]
    report = build_context_report(all_messages=msgs, sent_messages=msgs[-1:], adapter="universal",
                                  context_files=[{"path": "a.md", "bytes": 3}])
    data = json.loads(json.dumps(report.to_dict()))
    assert data["omitted_sequences"] == [1, 2]
    assert data["context_files"] == [{"path": "a.md", "bytes": 3}]
    assert data["attempts"] == 1
