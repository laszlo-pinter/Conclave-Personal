# tests/application/test_retention.py

import sqlite3
from datetime import datetime, timezone, timedelta

import pytest

from conclave.application.retention_service import RetentionService
from conclave.domain.participant import ParticipantType


def test_expired_conversations_are_deleted(service):
    conv = service.create_conversation()
    # Manuell created_at in die Vergangenheit setzen
    service._conversation_repository._connection.execute(
        "UPDATE conversations SET created_at = ? WHERE id = ?",
        ((datetime.now(timezone.utc) - timedelta(days=100)).isoformat(), conv.id),
    )
    retention = RetentionService(service)
    deleted = retention.purge_expired(retention_days=90)
    assert conv.id in deleted


def test_non_expired_conversations_are_kept(service):
    conv = service.create_conversation()
    retention = RetentionService(service)
    deleted = retention.purge_expired(retention_days=90)
    assert conv.id not in deleted


def test_purge_deletes_messages_and_participants(service):
    conv = service.create_conversation()
    service.register_participant(conv.id, "p1", ParticipantType.MODEL, "Claude")
    service.add_user_message(conv.id, "Hallo")

    service._conversation_repository._connection.execute(
        "UPDATE conversations SET created_at = ? WHERE id = ?",
        ((datetime.now(timezone.utc) - timedelta(days=200)).isoformat(), conv.id),
    )

    retention = RetentionService(service)
    retention.purge_expired(retention_days=90)

    # Conversation + Messages + Participants geloescht
    from conclave.domain.errors import ConversationNotFound
    with pytest.raises(ConversationNotFound):
        service.load_conversation(conv.id)


def test_dry_run_does_not_delete(service):
    conv = service.create_conversation()
    service._conversation_repository._connection.execute(
        "UPDATE conversations SET created_at = ? WHERE id = ?",
        ((datetime.now(timezone.utc) - timedelta(days=200)).isoformat(), conv.id),
    )

    retention = RetentionService(service)
    found = retention.purge_expired(retention_days=90, dry_run=True)
    assert conv.id in found

    # Conversation existiert noch
    loaded = service.load_conversation(conv.id)
    assert loaded.id == conv.id


def test_purge_returns_empty_when_nothing_expired(service):
    service.create_conversation()
    retention = RetentionService(service)
    deleted = retention.purge_expired(retention_days=90)
    assert deleted == []
