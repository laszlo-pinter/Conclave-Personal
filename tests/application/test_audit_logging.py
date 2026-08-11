# tests/application/test_audit_logging.py

from unittest.mock import MagicMock

import pytest

from conclave.application.adapter_registry import AdapterRegistry
from conclave.application.conversation_flow import ConversationFlowService
from conclave.domain.audit import AuditEntry
from conclave.domain.participant import ParticipantType


def _setup_with_audit(service, db_connection):
    """Richtet Service mit AuditRepository ein und gibt (conv_id, audit_repo) zurueck."""
    from conclave.infrastructure.sqlite.audit_repository import SQLiteAuditRepository

    audit_repo = SQLiteAuditRepository(db_connection)
    service.set_audit_repository(audit_repo)

    conv = service.create_conversation()
    service.register_participant(conv.id, "model-a", ParticipantType.MODEL, "Claude")
    service.add_user_message(conv.id, "Hallo")

    adapter = MagicMock()
    adapter.provider = "test"
    adapter.complete.return_value = "Antwort vom Modell"
    registry = AdapterRegistry()
    registry.register("model-a", adapter)
    service.set_adapter_registry(registry)

    return conv.id, audit_repo


def test_invoke_creates_audit_entry(service, db_connection):
    conv_id, audit_repo = _setup_with_audit(service, db_connection)

    service.invoke_participant(conv_id, "model-a")

    entries = audit_repo.list_by_conversation(conv_id)
    assert len(entries) == 1
    assert entries[0].operation == "invoke_participant"
    assert entries[0].conversation_id == conv_id
    assert entries[0].participant_id == "model-a"
    assert entries[0].success is True


def test_audit_entry_contains_no_message_content(service, db_connection):
    """Content gehoert nicht ins Laufprotokoll."""
    conv_id, audit_repo = _setup_with_audit(service, db_connection)

    service.invoke_participant(conv_id, "model-a")

    entry = audit_repo.list_by_conversation(conv_id)[0]
    # AuditEntry hat kein content-Feld
    assert not hasattr(entry, "content")
    # error_message sollte auch keinen Content enthalten
    assert entry.error_message is None


def test_failed_invoke_creates_audit_with_error(service, db_connection):
    from conclave.infrastructure.sqlite.audit_repository import SQLiteAuditRepository

    audit_repo = SQLiteAuditRepository(db_connection)
    service.set_audit_repository(audit_repo)

    conv = service.create_conversation()
    service.register_participant(conv.id, "model-a", ParticipantType.MODEL, "Claude")
    service.add_user_message(conv.id, "Hallo")

    adapter = MagicMock()
    adapter.provider = "test"
    adapter.complete.side_effect = RuntimeError("API down")
    registry = AdapterRegistry()
    registry.register("model-a", adapter)
    service.set_adapter_registry(registry)

    with pytest.raises(RuntimeError):
        service.invoke_participant(conv.id, "model-a")

    entries = audit_repo.list_by_conversation(conv.id)
    assert len(entries) == 1
    assert entries[0].success is False
    assert entries[0].error_message == "RuntimeError"


def test_no_audit_repo_means_no_audit(service):
    """Ohne AuditRepository wird kein Audit erstellt (Rueckwaertskompatibilitaet)."""
    conv = service.create_conversation()
    service.register_participant(conv.id, "model-a", ParticipantType.MODEL, "Claude")
    service.add_user_message(conv.id, "Hallo")

    adapter = MagicMock()
    adapter.provider = "test"
    adapter.complete.return_value = "Antwort"
    registry = AdapterRegistry()
    registry.register("model-a", adapter)
    service.set_adapter_registry(registry)

    # Kein set_audit_repository — soll nicht crashen
    service.invoke_participant(conv.id, "model-a")
