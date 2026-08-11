from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from conclave.application.adapter_registry import AdapterRegistry
from conclave.domain.participant import ParticipantType
from conclave.infrastructure.sqlite.run_repository import SQLiteRunRepository


def _setup(service, db_connection, adapter):
    run_repo = SQLiteRunRepository(db_connection)
    service.set_run_repository(run_repo)
    conv = service.create_conversation()
    service.register_participant(conv.id, "model-a", ParticipantType.MODEL, "Agent A")
    service.add_user_message(conv.id, "Hallo")
    registry = AdapterRegistry()
    registry.register("model-a", adapter)
    service.set_adapter_registry(registry)
    return conv.id, run_repo


def test_invoke_creates_succeeded_run(service, db_connection):
    adapter = MagicMock()
    adapter.provider = "test"
    adapter._model = "model-x"
    adapter.last_usage = SimpleNamespace(input_tokens=3, output_tokens=5)
    adapter.complete.return_value = "Antwort"
    conv_id, run_repo = _setup(service, db_connection, adapter)

    service.invoke_participant(conv_id, "model-a")

    runs = run_repo.list_by_conversation(conv_id)
    assert len(runs) == 1
    assert runs[0].kind == "invoke"
    assert runs[0].status == "succeeded"
    assert runs[0].participants == ["model-a"]
    assert runs[0].usage is not None
    assert runs[0].usage.total_tokens == 8


def test_failed_invoke_creates_failed_run(service, db_connection):
    adapter = MagicMock()
    adapter.provider = "test"
    adapter._model = "model-x"
    adapter.complete.side_effect = RuntimeError("down")
    conv_id, run_repo = _setup(service, db_connection, adapter)

    with pytest.raises(RuntimeError):
        service.invoke_participant(conv_id, "model-a")

    runs = run_repo.list_by_conversation(conv_id)
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert runs[0].error == "RuntimeError"
