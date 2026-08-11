# tests/infrastructure/test_universal/test_token_efficiency.py
"""Tests fuer Smart Truncation und Context Files."""

import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from conclave.domain.conversation import Conversation
from conclave.domain.message import Message, MessageAuthorType
from conclave.infrastructure.universal.adapter import (
    _smart_truncate,
    _load_context_files,
    _build_system_prompt,
)

_NOW = datetime.now(timezone.utc)


def _make_msg(seq: int, author_type=MessageAuthorType.USER, content="msg") -> Message:
    return Message(
        id=f"m{seq}",
        conversation_id="conv-1",
        author_type=author_type,
        author_id=None if author_type == MessageAuthorType.USER else "agent-1",
        content=f"{content}-{seq}",
        sequence=seq,
        created_at=_NOW,
    )


class TestSmartTruncate:
    def test_short_conversation_unchanged(self):
        msgs = [_make_msg(i) for i in range(1, 6)]
        result = _smart_truncate(msgs, max_messages=10)
        assert len(result) == 5

    def test_long_conversation_keeps_first_user_message(self):
        msgs = [_make_msg(1, MessageAuthorType.USER, "Aufgabe")]
        for i in range(2, 32):
            msgs.append(_make_msg(i, MessageAuthorType.MODEL, "antwort"))
        result = _smart_truncate(msgs, max_messages=5)
        assert len(result) == 5
        assert result[0].content == "Aufgabe-1"  # Erste User-Message
        assert result[-1].sequence == 31  # Letzte Message

    def test_first_user_message_not_duplicated_if_in_tail(self):
        msgs = [_make_msg(i) for i in range(1, 6)]
        result = _smart_truncate(msgs, max_messages=5)
        assert len(result) == 5
        # Keine Duplikate
        ids = [m.id for m in result]
        assert len(ids) == len(set(ids))

    def test_preserves_order(self):
        msgs = [_make_msg(1, MessageAuthorType.USER, "start")]
        for i in range(2, 12):
            msgs.append(_make_msg(i, MessageAuthorType.MODEL))
        result = _smart_truncate(msgs, max_messages=4)
        seqs = [m.sequence for m in result]
        assert seqs == [1, 9, 10, 11]

    def test_all_model_messages_no_first_user(self):
        msgs = [_make_msg(i, MessageAuthorType.MODEL) for i in range(1, 11)]
        result = _smart_truncate(msgs, max_messages=3)
        assert len(result) == 3
        assert result[-1].sequence == 10


class TestContextFiles:
    def test_load_context_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Erstelle Test-Datei
            with open(os.path.join(tmpdir, "aufgabe.md"), "w") as f:
                f.write("# Aufgabe 1\nMache X.")
            conv = Conversation(id="c1", rules=f"context_files: aufgabe.md")
            with patch.dict(os.environ, {"CONCLAVE_WORKSPACE": tmpdir}):
                result = _load_context_files(conv)
            assert "Aufgabe 1" in result
            assert "Mache X." in result

    def test_load_multiple_context_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "a.md"), "w") as f:
                f.write("Datei A")
            with open(os.path.join(tmpdir, "b.md"), "w") as f:
                f.write("Datei B")
            conv = Conversation(id="c1", rules="context_files: a.md, b.md")
            with patch.dict(os.environ, {"CONCLAVE_WORKSPACE": tmpdir}):
                result = _load_context_files(conv)
            assert "Datei A" in result
            assert "Datei B" in result

    def test_missing_file_ignored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            conv = Conversation(id="c1", rules="context_files: nonexistent.md")
            with patch.dict(os.environ, {"CONCLAVE_WORKSPACE": tmpdir}):
                result = _load_context_files(conv)
            assert result == ""

    def test_no_context_files_directive(self):
        conv = Conversation(id="c1", rules="Nur normale Regeln")
        result = _load_context_files(conv)
        assert result == ""

    def test_context_files_stripped_from_rules_in_system_prompt(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "ctx.md"), "w") as f:
                f.write("Kontext-Inhalt")
            conv = Conversation(id="c1", rules="context_files: ctx.md\nSei praezise.")
            with patch.dict(os.environ, {"CONCLAVE_WORKSPACE": tmpdir}):
                result = _build_system_prompt("Agent-Prompt", conv)
            assert "Kontext-Inhalt" in result
            assert "Sei praezise" in result
            assert "context_files:" not in result

    def test_path_traversal_blocked(self):
        conv = Conversation(id="c1", rules="context_files: ../../etc/passwd")
        result = _load_context_files(conv)
        assert result == ""
