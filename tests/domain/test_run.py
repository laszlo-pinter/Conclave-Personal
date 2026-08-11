from datetime import datetime, timezone

from conclave.domain.run import Run, UsageRecord


def test_usage_record_total_tokens_handles_missing_values():
    usage = UsageRecord(provider="test", model="m", input_tokens=12)

    assert usage.total_tokens == 12


def test_run_contains_personal_execution_metadata():
    started = datetime.now(timezone.utc)
    run = Run(
        id="run-1",
        conversation_id="conv-1",
        kind="invoke",
        participants=["agent-a"],
        started_at=started,
        finished_at=None,
        status="running",
    )

    assert run.conversation_id == "conv-1"
    assert run.participants == ["agent-a"]
    assert run.status == "running"
