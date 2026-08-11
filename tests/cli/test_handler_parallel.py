# tests/cli/test_handler_parallel.py

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from conclave.application.adapter_registry import AdapterRegistry
from conclave.cli.handler import CLIHandler
from conclave.domain.participant import ParticipantType


def _setup(service, participant_ids: list[str], responses: dict[str, str]) -> str:
    """Helper: Conversation + Participants + Async-Adapter einrichten."""
    handler = CLIHandler(service)
    conv_id = handler.new_conversation().data["conversation_id"]
    for pid in participant_ids:
        service.register_participant(conv_id, pid, ParticipantType.MODEL, pid)
    service.add_user_message(conv_id, "Startfrage")

    registry = AdapterRegistry()
    for pid, text in responses.items():
        adapter = MagicMock()
        adapter.complete = AsyncMock(return_value=text)
        registry.register(pid, adapter)
    service.set_adapter_registry(registry)

    return conv_id


def test_orchestrate_parallel_returns_success(service):
    conv_id = _setup(service, ["a", "b"], {"a": "Antwort A", "b": "Antwort B"})
    handler = CLIHandler(service)
    result = handler.orchestrate_parallel(conv_id, [["a", "b"]])

    assert result.success
    assert len(result.data["responses"]) == 2


def test_orchestrate_parallel_returns_contents(service):
    conv_id = _setup(service, ["a", "b"], {"a": "AA", "b": "BB"})
    handler = CLIHandler(service)
    result = handler.orchestrate_parallel(conv_id, [["a", "b"]])

    contents = {r["participant_id"]: r["content"] for r in result.data["responses"]}
    assert contents["a"] == "AA"
    assert contents["b"] == "BB"


def test_orchestrate_parallel_sequential_groups(service):
    conv_id = _setup(service, ["a", "b", "c"], {"a": "A", "b": "B", "c": "C"})
    handler = CLIHandler(service)
    result = handler.orchestrate_parallel(conv_id, [["a", "b"], ["c"]])

    assert result.success
    assert len(result.data["responses"]) == 3


def test_orchestrate_parallel_failure_returns_error(service):
    conv_id = _setup(service, ["a", "b"], {"a": "OK"})
    # b hat keinen Adapter → wird fehlschlagen
    handler = CLIHandler(service)
    result = handler.orchestrate_parallel(conv_id, [["a", "b"]])

    assert not result.success
    assert result.message != ""
