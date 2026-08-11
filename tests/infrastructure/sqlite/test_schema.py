import sqlite3
import uuid

from conclave.infrastructure.sqlite.schema import initialize_schema

def test_initialize_schema_creates_participants_created_at_column(db_connection):
    cursor = db_connection.execute("PRAGMA table_info(participants)")
    columns = [row[1] for row in cursor.fetchall()]

    assert "created_at" in columns

def test_initialize_schema_creates_runs_tables(db_connection):
    tables = {
        row[0]
        for row in db_connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

    assert "runs" in tables
    assert "usage_records" in tables

def test_participant_id_may_repeat_across_different_conversations():
    connection = sqlite3.connect(":memory:")
    initialize_schema(connection)

    participant_id = str(uuid.uuid4())
    conversation_1 = str(uuid.uuid4())
    conversation_2 = str(uuid.uuid4())

    connection.execute(
        "INSERT INTO conversations (id, status, created_at) VALUES (?, ?, ?)",
        (conversation_1, "active", "2026-03-24T00:00:00"),
    )
    connection.execute(
        "INSERT INTO conversations (id, status, created_at) VALUES (?, ?, ?)",
        (conversation_2, "active", "2026-03-24T00:00:00"),
    )

    connection.execute(
        """
        INSERT INTO participants (id, conversation_id, participant_type, name, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (participant_id, conversation_1, "user", "Alice", "2026-03-27T12:00:00"),
    )
    connection.execute(
        """
        INSERT INTO participants (id, conversation_id, participant_type, name, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (participant_id, conversation_2, "model", "GPT-Adapter", "2026-03-27T13:00:00"),
    )

    rows = connection.execute(
        "SELECT id, conversation_id FROM participants"
    ).fetchall()

    assert set(rows) == {
        (participant_id, conversation_1),
        (participant_id, conversation_2),
    }

def test_participant_id_must_be_unique_within_one_conversation():
    connection = sqlite3.connect(":memory:")
    initialize_schema(connection)

    participant_id = str(uuid.uuid4())
    conversation_id = str(uuid.uuid4())

    connection.execute(
        "INSERT INTO conversations (id, status, created_at) VALUES (?, ?, ?)",
        (conversation_id, "active", "2026-03-24T00:00:00"),
    )
    connection.execute(
        """
        INSERT INTO participants (id, conversation_id, participant_type, name, created_at)
        VALUES (?, ?, ?, ?,?)
        """,
        (participant_id, conversation_id, "user", "Alice", "2026-03-27T12:00:00"),
    )

    try:
        connection.execute(
            """
            INSERT INTO participants (id, conversation_id, participant_type, name, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (participant_id, conversation_id, "model", "GPT-Adapter", "2026-03-27T13:00:00"),
        )
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("Expected UNIQUE constraint violation for (conversation_id, id)")
