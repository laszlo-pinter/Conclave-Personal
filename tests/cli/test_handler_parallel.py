# tests/cli/test_handler_parallel.py

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from conclave.application.adapter_registry import AdapterRegistry
from conclave.cli.handler import CLIHandler
from conclave.domain.participant import ParticipantType


class DelayedAdapter:
    provider = "test"

    def __init__(self, response: str, delay: float):
        self._response = response
        self._delay = delay

    async def complete(self, conversation, participant):
        await asyncio.sleep(self._delay)
        return self._response


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


def test_orchestrate_parallel_stream_yields_responses_as_they_finish(service):
    handler = CLIHandler(service)
    conv_id = handler.new_conversation().data["conversation_id"]
    for participant_id in ["slow", "fast"]:
        service.register_participant(conv_id, participant_id, ParticipantType.MODEL, participant_id)
    service.add_user_message(conv_id, "Startfrage")

    registry = AdapterRegistry()
    registry.register("slow", DelayedAdapter("SLOW", 0.05))
    registry.register("fast", DelayedAdapter("FAST", 0.01))
    service.set_adapter_registry(registry)

    events = list(handler.orchestrate_parallel_stream(conv_id, [["slow", "fast"]]))
    responses = [event for event in events if event["event"] == "response"]

    assert [event["participant"] for event in responses] == ["fast", "slow"]
    assert [event["content"] for event in responses] == ["FAST", "SLOW"]
    loaded = service.load_conversation(conv_id)
    assert [message.author_id for message in loaded.messages[1:]] == ["fast", "slow"]


def test_orchestrate_parallel_stream_returns_stop_event_on_failure(service):
    conv_id = _setup(service, ["a", "b"], {"a": "OK"})
    handler = CLIHandler(service)

    events = list(handler.orchestrate_parallel_stream(conv_id, [["a", "b"]]))

    assert any(event["event"] == "error" and event["participant"] == "b" for event in events)
    assert events[-1]["event"] == "stop"
    assert events[-1]["reason"] == "error"
