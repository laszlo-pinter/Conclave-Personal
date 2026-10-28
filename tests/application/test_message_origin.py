"""Z4: messages.origin - Herkunft speichern, Prompt und Rollen unveraendert lassen."""

import dataclasses
import sqlite3

import pytest

from conclave.domain.conversation import Conversation
from conclave.domain.message import MessageAuthorType
from conclave.domain.participant import Participant, ParticipantType
from conclave.infrastructure.anthropic.adapter import AnthropicAdapter
from conclave.infrastructure.anthropic.async_adapter import AsyncAnthropicAdapter
from conclave.infrastructure.migrations import run_migrations
from conclave.infrastructure.openai.adapter import OpenAIAdapter
from conclave.infrastructure.openai.async_adapter import AsyncOpenAIAdapter
from conclave.infrastructure.sqlite.message_repository import SQLiteMessageRepository
from conclave.infrastructure.sqlite.schema import initialize_schema
from conclave.infrastructure.universal.adapter import UniversalAdapter


def _conversation(origin):
    conv = Conversation.create(topic="Herkunft")
    conv.id = "fest"                                     # gleicher System-Prompt in beiden Varianten
    conv.add_participant(Participant(id="p1", conversation_id="fest", participant_type=ParticipantType.MODEL, name="P1"))
    conv.add_participant(Participant(id="p2", conversation_id="fest", participant_type=ParticipantType.MODEL, name="P2"))
    conv.add_user_message("Frage von Laszlo", origin="human")
    conv.add_user_message("Hinweis von cc", origin=origin)
    conv.add_model_message("p1", "Antwort P1")
    conv.add_model_message("p2", "Antwort P2")
    conv.add_user_message("Noch ein Hinweis", origin=origin)
    return conv


def test_user_message_keeps_author_type_user_whatever_the_origin():
    conv = _conversation("agent")
    agent_messages = [m for m in conv.messages if m.origin == "agent"]
    assert len(agent_messages) == 2
    assert {m.author_type for m in agent_messages} == {MessageAuthorType.USER}
    assert all(m.origin is None for m in conv.messages if m.author_type == MessageAuthorType.MODEL)


@pytest.mark.parametrize("message_format", ["standard", "gemini"])
def test_universal_prompt_is_identical_for_agent_human_and_unknown_origin(message_format):
    adapter = UniversalAdapter(api_url="https://api.openai.com/v1/chat/completions", api_key="k", model="m",
                               message_format=message_format)
    participant = Participant(id="p1", conversation_id="fest", participant_type=ParticipantType.MODEL, name="P1")
    bodies = [adapter.prepare_request(_conversation(o), participant).body for o in ("agent", "human", None)]
    assert bodies[0] == bodies[1] == bodies[2]
    assert "agent" not in str(bodies[0]).lower()          # kein Hinweis auf die Herkunft im Prompt


@pytest.mark.parametrize("build", [
    AnthropicAdapter._build_messages, AsyncAnthropicAdapter._build_messages,
    OpenAIAdapter._build_input, AsyncOpenAIAdapter._build_input,
])
def test_native_adapter_roles_are_unchanged(build):
    results = [build(None, _conversation(o)) for o in ("agent", "human", None)]
    assert results[0] == results[1] == results[2]
    assert [m["role"] for m in results[0]] == ["user", "user", "assistant", "assistant", "user"]


def test_sqlite_roundtrip_and_old_rows_are_null():
    conn = sqlite3.connect(":memory:")
    initialize_schema(conn)
    conn.execute("INSERT INTO conversations (id, status, topic, created_at) VALUES ('c', 'open', '', '2026')")
    repo = SQLiteMessageRepository(conn, autocommit=True)
    conv = Conversation(id="c", topic="")
    for origin in ("agent", "human", None):
        repo.save(conv.add_user_message(f"von {origin}", origin=origin))
    assert [m.origin for m in repo.list_by_conversation_id("c")] == ["agent", "human", None]


def test_migration_adds_column_and_keeps_old_messages_unknown():
    conn = sqlite3.connect(":memory:")
    initialize_schema(conn)
    # Stand v0.4.0: Tabelle ohne Spalte origin, Migration 011 noch nicht gelaufen
    conn.executescript("""
        CREATE TABLE messages_alt AS SELECT id, conversation_id, author_type, author_id, content, sequence,
                                            created_at FROM messages;
        DROP TABLE messages;
        ALTER TABLE messages_alt RENAME TO messages;
        DELETE FROM _migrations WHERE id = '011_message_origin';
        INSERT INTO conversations (id, status, topic, created_at) VALUES ('c', 'open', '', '2026');
        INSERT INTO messages VALUES ('m1', 'c', 'user', NULL, 'alt', 1, '2026-10-27T00:00:00+00:00');
    """)
    assert "011_message_origin" in run_migrations(conn)
    assert run_migrations(conn) == []
    loaded = SQLiteMessageRepository(conn).list_by_conversation_id("c")
    assert [(m.content, m.origin) for m in loaded] == [("alt", None)]


def test_replace_keeps_dataclass_default():
    msg = _conversation(None).messages[0]
    assert dataclasses.replace(msg, origin="agent").origin == "agent"
