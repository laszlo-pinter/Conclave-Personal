"""#94 (P2): Die Herkunft eines Laufs bleibt beim Laden erhalten (SQLite) und steht in der Ausgabe."""

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

from conclave.domain.run import Run, UsageRecord
from conclave.infrastructure.sqlite.run_repository import SQLiteRunRepository
from conclave.infrastructure.sqlite.schema import initialize_schema


def _run(started, origin=None):
    return Run(id=str(uuid.uuid4()), conversation_id="c1", kind="invoke", participants=["m1"], started_at=started,
               finished_at=started, status="success", usage=UsageRecord("p", "m", 10, 0), origin=origin)


def test_origin_survives_the_roundtrip_on_sqlite():
    conn = sqlite3.connect(":memory:")
    initialize_schema(conn)
    conn.execute("INSERT INTO conversations (id, topic, status, created_at) VALUES ('c1', '', 'active', ?)",
                 (datetime.now(UTC).isoformat(),))
    repo = SQLiteRunRepository(conn)
    now = datetime.now(UTC)
    agent, human = _run(now, "agent"), _run(now - timedelta(seconds=1))
    repo.save(agent)
    repo.save(human)
    assert repo.get(agent.id).origin == "agent" and repo.get(human.id).origin is None
    assert [r.origin for r in repo.list_by_conversation("c1")] == ["agent", None]
    assert [r.origin for r in repo.list_all()] == ["agent", None]


def test_run_output_names_the_origin():
    from conclave.cli.handler import CLIHandler
    run = _run(datetime.now(UTC), "agent")
    assert CLIHandler._run_to_dict(object.__new__(CLIHandler), run)["origin"] == "agent"
