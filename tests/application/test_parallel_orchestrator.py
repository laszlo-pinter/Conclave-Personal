# tests/application/test_parallel_orchestrator.py

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from conclave.application.adapter_registry import AdapterRegistry
from conclave.application.conversation_flow import ConversationFlowService
from conclave.application.orchestrator import ParallelOrchestrator
from conclave.domain.participant import ParticipantType


def _setup_conversation(service, participant_ids: list[str]) -> str:
    """Helper: Erstellt Conversation mit User-Message und registriert Participants."""
    conversation = service.create_conversation()
    for pid in participant_ids:
        service.register_participant(conversation.id, pid, ParticipantType.MODEL, pid)
    service.add_user_message(conversation.id, "Startfrage")
    return conversation.id


def _setup_async_registry(service, adapters: dict[str, str]) -> None:
    """Helper: Registriert async Adapter mit vordefinierten Antworten."""
    registry = AdapterRegistry()
    for pid, response_text in adapters.items():
        adapter = MagicMock()
        adapter.complete = AsyncMock(return_value=response_text)
        registry.register(pid, adapter)
    service.set_adapter_registry(registry)


@pytest.mark.asyncio
async def test_parallel_single_group_invokes_all(service):
    """Eine Gruppe mit mehreren Participants wird parallel aufgerufen."""
    conv_id = _setup_conversation(service, ["model-a", "model-b"])
    _setup_async_registry(service, {"model-a": "Antwort A", "model-b": "Antwort B"})

    orchestrator = ParallelOrchestrator(service)
    result = await orchestrator.run(conv_id, groups=[["model-a", "model-b"]])

    assert result.success is True
    assert len(result.responses) == 2
    contents = {r.participant_id: r.content for r in result.responses}
    assert contents["model-a"] == "Antwort A"
    assert contents["model-b"] == "Antwort B"


@pytest.mark.asyncio
async def test_parallel_sequential_groups(service):
    """Mehrere Gruppen werden sequentiell ausgeführt. Zweite Gruppe sieht Antworten der ersten."""
    conv_id = _setup_conversation(service, ["model-a", "model-b", "model-c"])
    _setup_async_registry(service, {
        "model-a": "A", "model-b": "B", "model-c": "Synthese",
    })

    orchestrator = ParallelOrchestrator(service)
    result = await orchestrator.run(conv_id, groups=[["model-a", "model-b"], ["model-c"]])

    assert result.success is True
    assert len(result.responses) == 3
    assert result.responses[2].participant_id == "model-c"


@pytest.mark.asyncio
async def test_parallel_response_order_matches_input(service):
    """Reihenfolge der Responses entspricht der Input-Sequenz innerhalb einer Gruppe."""
    conv_id = _setup_conversation(service, ["model-a", "model-b"])
    _setup_async_registry(service, {"model-a": "A", "model-b": "B"})

    orchestrator = ParallelOrchestrator(service)
    result = await orchestrator.run(conv_id, groups=[["model-a", "model-b"]])

    assert result.responses[0].participant_id == "model-a"
    assert result.responses[1].participant_id == "model-b"


@pytest.mark.asyncio
async def test_parallel_partial_failure(service):
    """Fehlschlag eines Participants bricht nicht die anderen ab."""
    conv_id = _setup_conversation(service, ["model-a", "model-b"])

    registry = AdapterRegistry()

    adapter_a = MagicMock()
    adapter_a.complete = AsyncMock(return_value="Antwort A")
    registry.register("model-a", adapter_a)

    adapter_b = MagicMock()
    adapter_b.complete = AsyncMock(side_effect=RuntimeError("Modell-Fehler"))
    registry.register("model-b", adapter_b)

    service.set_adapter_registry(registry)

    orchestrator = ParallelOrchestrator(service)
    result = await orchestrator.run(conv_id, groups=[["model-a", "model-b"]])

    assert result.success is False
    # model-a sollte trotzdem eine Antwort haben
    assert any(r.participant_id == "model-a" for r in result.responses)
    assert result.error != ""


@pytest.mark.asyncio
async def test_parallel_single_participant_group(service):
    """Einzelner Participant in einer Gruppe funktioniert."""
    conv_id = _setup_conversation(service, ["model-a"])
    _setup_async_registry(service, {"model-a": "Solo-Antwort"})

    orchestrator = ParallelOrchestrator(service)
    result = await orchestrator.run(conv_id, groups=[["model-a"]])

    assert result.success is True
    assert len(result.responses) == 1
    assert result.responses[0].content == "Solo-Antwort"


@pytest.mark.asyncio
async def test_parallel_empty_groups(service):
    """Leere Gruppen-Liste ergibt leeres Ergebnis."""
    conv_id = _setup_conversation(service, [])

    orchestrator = ParallelOrchestrator(service)
    result = await orchestrator.run(conv_id, groups=[])

    assert result.success is True
    assert len(result.responses) == 0
