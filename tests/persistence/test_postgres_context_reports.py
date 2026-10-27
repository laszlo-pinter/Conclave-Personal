"""Kontext-Reports gegen ein echtes PostgreSQL.

SQLite prueft Fremdschluessel nur mit PRAGMA foreign_keys; Postgres immer.
Laeuft nur mit CONCLAVE_TEST_POSTGRES_DSN (CI-Job "postgres"); lokal sonst
uebersprungen. Jeder Test beginnt mit einem leeren Schema "public".
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

DSN = os.environ.get("CONCLAVE_TEST_POSTGRES_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="CONCLAVE_TEST_POSTGRES_DSN nicht gesetzt")

psycopg2 = pytest.importorskip("psycopg2")
httpx = pytest.importorskip("httpx")

LEGACY_SCHEMA = Path(__file__).parent / "data" / "postgres_schema_v0_2_3.sql"
API_URL = "https://api.openai.com/v1/chat/completions"


@pytest.fixture
def pg():
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE")
        cur.execute("CREATE SCHEMA public")
    yield conn
    conn.close()


def _ok(text="Antwort", usage=(42, 7)):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}],
                                     "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1]}},
                          request=httpx.Request("POST", API_URL))


def _bad(*a, **k):
    return httpx.Response(400, json={"error": {"message": "kaputt"}}, request=httpx.Request("POST", API_URL))


class _Stream:
    def __init__(self, *a, **k):
        self._lines = ['data: {"choices":[{"delta":{"content":"Hi"}}]}', "",
                       'data: {"choices":[],"usage":{"prompt_tokens":9,"completion_tokens":2}}', "",
                       "data: [DONE]", ""]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_lines(self):
        return iter(self._lines)


@pytest.fixture
def env(pg, tmp_path, monkeypatch):
    from conclave.api.server import _build_postgres
    from conclave.application.adapter_registry import AdapterRegistry
    from conclave.cli.config import ConclaveConfig
    from conclave.cli.handler import CLIHandler
    from conclave.domain.participant import ParticipantType
    from conclave.infrastructure.universal.adapter import UniversalAdapter
    from conclave.infrastructure.universal.resilient import ResilientAdapter

    monkeypatch.setenv("CONCLAVE_SECRET_KEY_FILE", str(tmp_path / "secret.key"))
    service, _agents, conn = _build_postgres(ConclaveConfig(db_provider="postgres", db_dsn=DSN))
    registry = AdapterRegistry()
    for pid in ("p1", "p2"):
        registry.register(pid, ResilientAdapter(UniversalAdapter(api_url=API_URL, api_key="k", model="m"),
                                                sleep_fn=lambda s: None))
    service.set_adapter_registry(registry)
    conv = service.create_conversation(topic="Postgres")
    for pid in ("p1", "p2"):
        service.register_participant(conversation_id=conv.id, participant_id=pid,
                                     participant_type=ParticipantType.MODEL, name=pid.upper())
    service.set_rules(conv.id, "context_files: fehlt.md\nSei knapp.")
    service.add_user_message(conv.id, "Frage")
    yield service, CLIHandler(service), conv.id, conn
    conn.close()


def test_v023_database_migrates_without_data_loss(pg):
    from conclave.infrastructure.postgres.schema import initialize_schema

    with pg.cursor() as cur:
        cur.execute(LEGACY_SCHEMA.read_text(encoding="utf-8"))
        cur.execute("INSERT INTO conversations (id, status, topic, floor, rules, created_at) "
                    "VALUES ('alt', 'open', 'Alt', NULL, 'Sei knapp.', now())")
        cur.execute("INSERT INTO messages (id, conversation_id, author_type, author_id, content, sequence, created_at) "
                    "VALUES ('m1', 'alt', 'user', NULL, 'Hallo', 1, now())")
        cur.execute("SELECT to_regclass('context_reports')")
        assert cur.fetchone()[0] is None

    initialize_schema(pg)
    initialize_schema(pg)                       # zweiter Start: idempotent

    with pg.cursor() as cur:
        cur.execute("SELECT topic, rules FROM conversations WHERE id = 'alt'")
        assert cur.fetchone() == ("Alt", "Sei knapp.")
        cur.execute("SELECT count(*) FROM messages")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT id FROM _migrations WHERE id = '007_context_reports'")
        assert cur.fetchone() is not None


def test_context_reports_have_enforced_foreign_keys(env):
    _service, _handler, _conv_id, conn = env
    with conn.cursor() as cur:
        cur.execute("""
            SELECT kcu.column_name, ccu.table_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage ccu ON tc.constraint_name = ccu.constraint_name
            WHERE tc.table_name = 'context_reports' AND tc.constraint_type = 'FOREIGN KEY'
            ORDER BY 1
        """)
        assert cur.fetchall() == [("conversation_id", "conversations"), ("message_id", "messages"),
                                  ("run_id", "runs")]
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cur.execute("INSERT INTO context_reports (id, conversation_id, participant_id, message_id, run_id, "
                        "created_at, report_json) VALUES ('x', 'gibtsnicht', 'p', NULL, NULL, now(), '{}')")


def test_invoke_failure_and_stream_store_linked_reports(env):
    service, handler, conv_id, _conn = env
    with patch("httpx.post", lambda *a, **k: _ok()):
        result = handler.invoke_participant(conv_id, "p1")
    record = service.get_context_report_for_message(result.data["message_id"])
    assert record.run_id and record.input_tokens == 42
    assert record.report.skipped_context_files[0]["path"] == "fehlt.md"   # Regeln aus Postgres

    with patch("httpx.post", _bad), pytest.raises(ValueError):
        handler.invoke_participant(conv_id, "p1")
    failed = [r for r in service.list_context_reports(conv_id) if r.message_id is None]
    assert len(failed) == 1 and failed[0].run_id

    with patch("httpx.stream", _Stream):
        assert "".join(service.stream_participant(conv_id, "p1")) == "Hi"
    last = service.load_conversation(conv_id).messages[-1]
    assert service.get_context_report_for_message(last.id).input_tokens == 9


def test_parallel_paths_link_reports_and_delete_removes_everything(env):
    service, handler, conv_id, conn = env
    with patch("httpx.post", lambda *a, **k: _ok()):
        result = handler.orchestrate_parallel(conv_id, [["p1", "p2"]])
        events = list(handler.orchestrate_parallel_stream(conv_id, [["p1", "p2"]]))
    assert result.success
    assert all(service.get_context_report_for_message(r["message_id"]) for r in result.data["responses"])
    assert sum(1 for e in events if e["event"] == "response" and e.get("context")) == 2

    with patch("httpx.post", lambda *a, **k: _ok("fertig @done")):
        loop = list(handler.auto_loop(conv_id, ["p1"], max_rounds=1))
    assert any(e["event"] == "response" and e.get("context") for e in loop)

    shown = handler.show_conversation(conv_id).data
    assert len([m for m in shown["messages"] if m.get("context")]) == 5
    assert handler.context_preview(conv_id, "p1").success
    assert len(handler.export_conversation(conv_id).data["context_reports"]) == 5

    service.delete_conversation(conv_id)
    with conn.cursor() as cur:
        for table, column in (("context_reports", "conversation_id"), ("runs", "conversation_id"),
                              ("usage_records", "conversation_id"), ("messages", "conversation_id"),
                              ("conversations", "id")):
            cur.execute(f"SELECT count(*) FROM {table} WHERE {column} = %s", (conv_id,))  # nosec B608 - feste Namen
            assert cur.fetchone()[0] == 0, table
