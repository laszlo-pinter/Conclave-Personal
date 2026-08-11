# tests/infrastructure/sqlite/test_audit_repository.py

import sqlite3
from datetime import datetime, timezone, timedelta

import pytest

from conclave.domain.audit import AuditEntry
from conclave.infrastructure.sqlite.audit_repository import SQLiteAuditRepository
from conclave.infrastructure.sqlite.schema import initialize_schema


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    initialize_schema(conn)
    yield conn
    conn.close()


def _make_entry(
    id: str = "a1",
    conversation_id: str = "conv-1",
    participant_id: str = "p1",
    provider: str = "anthropic",
    model: str = "claude-sonnet-4-20250514",
    success: bool = True,
    timestamp: datetime | None = None,
    **kwargs,
) -> AuditEntry:
    return AuditEntry(
        id=id,
        timestamp=timestamp or datetime.now(timezone.utc),
        operation="invoke_participant",
        conversation_id=conversation_id,
        participant_id=participant_id,
        provider=provider,
        model=model,
        success=success,
        **kwargs,
    )


class TestSaveAndLoad:
    def test_save_and_list_by_conversation(self, db):
        repo = SQLiteAuditRepository(db)
        repo.save(_make_entry())

        entries = repo.list_by_conversation("conv-1")
        assert len(entries) == 1
        assert entries[0].id == "a1"
        assert entries[0].provider == "anthropic"

    def test_roundtrip_preserves_all_fields(self, db):
        repo = SQLiteAuditRepository(db)
        original = _make_entry(
            error_message="Timeout",
            user_id="user-42",
        )
        repo.save(original)

        loaded = repo.list_by_conversation("conv-1")[0]
        assert loaded.operation == original.operation
        assert loaded.participant_id == original.participant_id
        assert loaded.model == original.model
        assert loaded.success == original.success
        assert loaded.error_message == "Timeout"
        assert loaded.user_id == "user-42"

    def test_list_by_conversation_filters(self, db):
        repo = SQLiteAuditRepository(db)
        repo.save(_make_entry(id="a1", conversation_id="c1"))
        repo.save(_make_entry(id="a2", conversation_id="c2"))

        assert len(repo.list_by_conversation("c1")) == 1
        assert len(repo.list_by_conversation("c2")) == 1
        assert len(repo.list_by_conversation("c3")) == 0


class TestDateRangeQuery:
    def test_list_by_date_range(self, db):
        repo = SQLiteAuditRepository(db)
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)
        tomorrow = now + timedelta(days=1)

        repo.save(_make_entry(id="a1", timestamp=now))
        repo.save(_make_entry(id="a2", timestamp=yesterday - timedelta(hours=1)))

        entries = repo.list_by_date_range(yesterday, tomorrow)
        assert len(entries) == 1
        assert entries[0].id == "a1"

    def test_list_by_date_range_empty(self, db):
        repo = SQLiteAuditRepository(db)
        now = datetime.now(timezone.utc)
        repo.save(_make_entry(timestamp=now))

        future_start = now + timedelta(days=10)
        future_end = now + timedelta(days=20)
        assert len(repo.list_by_date_range(future_start, future_end)) == 0
