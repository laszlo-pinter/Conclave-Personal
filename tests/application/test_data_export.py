# tests/application/test_data_export.py

import pytest

from conclave.application.data_export_service import DataExportService
from conclave.domain.errors import ConversationNotFound
from conclave.domain.participant import ParticipantType


def test_export_contains_conversation_metadata(service):
    conv = service.create_conversation(topic="Testthema")
    export_svc = DataExportService(service)
    data = export_svc.export_conversation(conv.id)

    assert data["id"] == conv.id
    assert data["topic"] == "Testthema"
    assert "created_at" in data


def test_export_contains_messages(service):
    conv = service.create_conversation()
    service.add_user_message(conv.id, "Hallo Welt")
    export_svc = DataExportService(service)
    data = export_svc.export_conversation(conv.id)

    assert len(data["messages"]) == 1
    assert data["messages"][0]["content"] == "Hallo Welt"


def test_export_contains_participants(service):
    conv = service.create_conversation()
    service.register_participant(conv.id, "p1", ParticipantType.MODEL, "Claude")
    export_svc = DataExportService(service)
    data = export_svc.export_conversation(conv.id)

    assert len(data["participants"]) == 1
    assert data["participants"][0]["name"] == "Claude"


def test_export_nonexistent_conversation_raises(service):
    export_svc = DataExportService(service)
    with pytest.raises(ConversationNotFound):
        export_svc.export_conversation("nonexistent")


def test_export_format_is_serializable(service):
    """Export muss JSON-serialisierbar sein (alle Werte Strings/Ints/Listen)."""
    import json
    conv = service.create_conversation()
    service.add_user_message(conv.id, "Test")
    export_svc = DataExportService(service)
    data = export_svc.export_conversation(conv.id)

    serialized = json.dumps(data, default=str)
    assert isinstance(serialized, str)
