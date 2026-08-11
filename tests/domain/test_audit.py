# tests/domain/test_audit.py

from datetime import datetime, timezone

from conclave.domain.audit import AuditEntry


def test_audit_entry_has_required_fields():
    entry = AuditEntry(
        id="a1",
        timestamp=datetime.now(timezone.utc),
        operation="invoke_participant",
        conversation_id="conv-1",
        participant_id="p1",
        provider="anthropic",
        model="claude-sonnet-4-20250514",
        success=True,
    )
    assert entry.id == "a1"
    assert entry.operation == "invoke_participant"
    assert entry.provider == "anthropic"
    assert entry.success is True


def test_audit_entry_optional_fields_default_none():
    entry = AuditEntry(
        id="a2",
        timestamp=datetime.now(timezone.utc),
        operation="stream_participant",
        conversation_id="conv-1",
        participant_id="p1",
        provider="openai",
        model="gpt-4o",
        success=False,
    )
    assert entry.error_message is None
    assert entry.user_id is None


def test_audit_entry_with_error():
    entry = AuditEntry(
        id="a3",
        timestamp=datetime.now(timezone.utc),
        operation="invoke_participant",
        conversation_id="conv-1",
        participant_id="p1",
        provider="anthropic",
        model="claude-sonnet-4-20250514",
        success=False,
        error_message="API rate limit exceeded",
    )
    assert entry.success is False
    assert entry.error_message == "API rate limit exceeded"
