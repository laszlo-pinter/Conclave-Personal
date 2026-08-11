# tests/application/test_orchestrator.py

import pytest

from conclave.application.orchestrator import Orchestrator, OrchestratorResult
from conclave.application.adapter_registry import AdapterRegistry
from conclave.domain.conversation import Conversation
from conclave.domain.participant import Participant, ParticipantType
from conclave.domain.message import MessageAuthorType


class FakeAdapter:
    provider = "test"
    def __init__(self, response: str):
        self._response = response
        self.calls: list[tuple[str, int]] = []  # (participant_id, message_count)

    def complete(self, conversation: Conversation, participant: Participant) -> str:
        self.calls.append((participant.id, len(conversation.messages)))
        return self._response


def setup_conversation(service):
    conversation = service.create_conversation()
    service.register_participant(
        conversation_id=conversation.id,
        participant_id="model-a",
        participant_type=ParticipantType.MODEL,
        name="Model A",
    )
    service.register_participant(
        conversation_id=conversation.id,
        participant_id="model-b",
        participant_type=ParticipantType.MODEL,
        name="Model B",
    )
    service.add_user_message(conversation.id, "Startfrage")
    return conversation


# ── Grundfunktion ──────────────────────────────────────────────────────────

def test_orchestrator_runs_single_participant(service):
    adapter_a = FakeAdapter("Antwort A")
    registry = AdapterRegistry()
    registry.register("model-a", adapter_a)
    service.set_adapter_registry(registry)

    conversation = setup_conversation(service)
    orchestrator = Orchestrator(service)

    result = orchestrator.run(
        conversation_id=conversation.id,
        sequence=["model-a"],
    )

    assert result.success
    assert len(result.responses) == 1
    assert result.responses[0].participant_id == "model-a"
    assert result.responses[0].content == "Antwort A"


def test_orchestrator_runs_multiple_participants_in_order(service):
    adapter_a = FakeAdapter("Antwort A")
    adapter_b = FakeAdapter("Antwort B")
    registry = AdapterRegistry()
    registry.register("model-a", adapter_a)
    registry.register("model-b", adapter_b)
    service.set_adapter_registry(registry)

    conversation = setup_conversation(service)
    orchestrator = Orchestrator(service)

    result = orchestrator.run(
        conversation_id=conversation.id,
        sequence=["model-a", "model-b"],
    )

    assert result.success
    assert len(result.responses) == 2
    assert result.responses[0].participant_id == "model-a"
    assert result.responses[1].participant_id == "model-b"


def test_orchestrator_each_participant_sees_previous_responses(service):
    adapter_a = FakeAdapter("Antwort A")
    adapter_b = FakeAdapter("Antwort B")
    registry = AdapterRegistry()
    registry.register("model-a", adapter_a)
    registry.register("model-b", adapter_b)
    service.set_adapter_registry(registry)

    conversation = setup_conversation(service)
    orchestrator = Orchestrator(service)

    orchestrator.run(
        conversation_id=conversation.id,
        sequence=["model-a", "model-b"],
    )

    # model-a sieht 1 Message (user), model-b sieht 2 (user + A's Antwort)
    assert adapter_a.calls[0][1] == 1
    assert adapter_b.calls[0][1] == 2


def test_orchestrator_persists_all_responses(service):
    adapter_a = FakeAdapter("Antwort A")
    adapter_b = FakeAdapter("Antwort B")
    registry = AdapterRegistry()
    registry.register("model-a", adapter_a)
    registry.register("model-b", adapter_b)
    service.set_adapter_registry(registry)

    conversation = setup_conversation(service)
    orchestrator = Orchestrator(service)

    orchestrator.run(
        conversation_id=conversation.id,
        sequence=["model-a", "model-b"],
    )

    loaded = service.load_conversation(conversation.id)
    assert len(loaded.messages) == 3  # 1 user + 2 model
    assert loaded.messages[1].content == "Antwort A"
    assert loaded.messages[2].content == "Antwort B"


def test_orchestrator_round_robin(service):
    adapter_a = FakeAdapter("A")
    adapter_b = FakeAdapter("B")
    registry = AdapterRegistry()
    registry.register("model-a", adapter_a)
    registry.register("model-b", adapter_b)
    service.set_adapter_registry(registry)

    conversation = setup_conversation(service)
    orchestrator = Orchestrator(service)

    result = orchestrator.run(
        conversation_id=conversation.id,
        sequence=["model-a", "model-b", "model-a"],
    )

    assert len(result.responses) == 3
    assert result.responses[0].participant_id == "model-a"
    assert result.responses[1].participant_id == "model-b"
    assert result.responses[2].participant_id == "model-a"
    assert len(adapter_a.calls) == 2
    assert len(adapter_b.calls) == 1


# ── Fehlerbehandlung ───────────────────────────────────────────────────────

def test_orchestrator_stops_on_missing_adapter(service):
    registry = AdapterRegistry()
    registry.register("model-a", FakeAdapter("A"))
    service.set_adapter_registry(registry)

    conversation = setup_conversation(service)
    orchestrator = Orchestrator(service)

    result = orchestrator.run(
        conversation_id=conversation.id,
        sequence=["model-a", "model-b"],  # model-b hat keinen Adapter
    )

    assert not result.success
    assert len(result.responses) == 1   # model-a hat geantwortet
    assert "model-b" in result.error


def test_orchestrator_unknown_conversation_returns_failure(service):
    orchestrator = Orchestrator(service)

    result = orchestrator.run(
        conversation_id="unbekannt",
        sequence=["model-a"],
    )

    assert not result.success
    assert "unbekannt" in result.error
