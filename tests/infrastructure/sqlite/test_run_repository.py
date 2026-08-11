from datetime import datetime, timezone

from conclave.domain.run import Run, UsageRecord
from conclave.infrastructure.sqlite.run_repository import SQLiteRunRepository


def _insert_conversation(connection, conversation_id="conv-1"):
    connection.execute(
        "INSERT INTO conversations (id, status, created_at) VALUES (?, ?, ?)",
        (conversation_id, "active", datetime.now(timezone.utc).isoformat()),
    )


def test_save_and_get_run(db_connection):
    _insert_conversation(db_connection)
    repo = SQLiteRunRepository(db_connection)
    run = Run(
        id="run-1",
        conversation_id="conv-1",
        kind="invoke",
        participants=["agent-a"],
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        status="succeeded",
        usage=UsageRecord(provider="test", model="m", input_tokens=3, output_tokens=5),
    )

    repo.save(run)

    loaded = repo.get("run-1")
    assert loaded is not None
    assert loaded.kind == "invoke"
    assert loaded.participants == ["agent-a"]
    assert loaded.usage is not None
    assert loaded.usage.total_tokens == 8


def test_list_by_conversation_filters_runs(db_connection):
    _insert_conversation(db_connection, "conv-1")
    _insert_conversation(db_connection, "conv-2")
    repo = SQLiteRunRepository(db_connection)
    now = datetime.now(timezone.utc)
    repo.save(Run(id="run-1", conversation_id="conv-1", kind="invoke",
                  participants=["a"], started_at=now, finished_at=now, status="succeeded"))
    repo.save(Run(id="run-2", conversation_id="conv-2", kind="invoke",
                  participants=["b"], started_at=now, finished_at=now, status="succeeded"))

    runs = repo.list_by_conversation("conv-1")

    assert [r.id for r in runs] == ["run-1"]
