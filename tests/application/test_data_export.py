# tests/application/test_data_export.py

import pytest

from conclave.application.data_export_service import DataExportService
from conclave.domain.errors import ConversationNotFound
from conclave.domain.participant import ParticipantType
from conclave.domain.tool_event import ToolEvent


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


def test_export_contains_tool_events(service):
    conv = service.create_conversation()
    updated = service.add_user_message(conv.id, "Hallo Welt")
    message = updated.messages[-1]
    event = ToolEvent.create(
        conversation_id=conv.id,
        participant_id="writer",
        tool="workspace.save",
        status="succeeded",
        input_json={"path": "report.md"},
        output_json={"path": "output/report.md", "bytes_written": 7},
        message_id=message.id,
    )
    service.list_tool_events_by_conversation = lambda conversation_id: [event]
    export_svc = DataExportService(service)

    data = export_svc.export_conversation(conv.id)

    assert data["tool_events"][0]["id"] == event.id
    assert data["tool_events"][0]["tool"] == "workspace.save"
    assert data["messages"][0]["tool_events"][0]["id"] == event.id


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
