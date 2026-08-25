from conclave.domain.tool_event import ToolEvent
from conclave.infrastructure.sqlite.tool_event_repository import SQLiteToolEventRepository


def _insert_conversation_and_message(connection, conversation_id="conv-1", message_id="msg-1"):
    connection.execute(
        "INSERT INTO conversations (id, status, topic, created_at) VALUES (?, ?, ?, ?)",
        (conversation_id, "active", "", "2026-01-01T00:00:00+00:00"),
    )
    connection.execute(
        """
        INSERT INTO messages (
            id, conversation_id, author_type, author_id, content, sequence, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (message_id, conversation_id, "model", "writer", "content", 1, "2026-01-01T00:00:01+00:00"),
    )


def test_tool_event_repository_saves_and_loads_by_conversation(db_connection):
    _insert_conversation_and_message(db_connection)
    repo = SQLiteToolEventRepository(db_connection)
    event = ToolEvent.create(
        conversation_id="conv-1",
        participant_id="writer",
        tool="workspace.save",
        status="succeeded",
        input_json={"path": "report.md"},
        output_json={"path": "output/report.md", "bytes_written": 12},
        message_id="msg-1",
    )

    repo.save(event)

    loaded = repo.list_by_conversation("conv-1")
    assert len(loaded) == 1
    assert loaded[0].id == event.id
    assert loaded[0].tool == "workspace.save"
    assert loaded[0].status == "succeeded"
    assert loaded[0].input_json == {"path": "report.md"}
    assert loaded[0].output_json["path"] == "output/report.md"
    assert loaded[0].message_id == "msg-1"


def test_tool_event_repository_lists_by_message(db_connection):
    _insert_conversation_and_message(db_connection, message_id="msg-1")
    _insert_conversation_and_message(db_connection, conversation_id="conv-2", message_id="msg-2")
    repo = SQLiteToolEventRepository(db_connection)
    repo.save(ToolEvent.create(
        conversation_id="conv-1",
        participant_id="writer",
        tool="workspace.save",
        status="failed",
        input_json={"path": "blocked.md"},
        error="path_not_allowed",
        message_id="msg-1",
    ))
    repo.save(ToolEvent.create(
        conversation_id="conv-2",
        participant_id="writer",
        tool="workspace.save",
        status="succeeded",
        input_json={"path": "other.md"},
        message_id="msg-2",
    ))

    loaded = repo.list_by_message("msg-1")

    assert len(loaded) == 1
    assert loaded[0].status == "failed"
    assert loaded[0].error == "path_not_allowed"
