# tests/application/test_floor_service.py

import pytest
from conclave.domain.errors import FloorNotGranted, NoFloorGranted, ParticipantNotRegistered
from conclave.domain.participant import ParticipantType
from conclave.domain.conversation import Conversation
from conclave.domain.participant import Participant


def setup(service):
    conv = service.create_conversation(topic="Klimawandel")
    service.register_participant(conv.id, "p1", ParticipantType.MODEL, "Model A")
    service.register_participant(conv.id, "p2", ParticipantType.MODEL, "Model B")
    return conv


# ── set_topic ─────────────────────────────────────────────────────────────

def test_create_conversation_with_topic(service):
    conv = service.create_conversation(topic="KI-Ethik")
    loaded = service.load_conversation(conv.id)
    assert loaded.topic == "KI-Ethik"


def test_set_topic_updates_conversation(service):
    conv = service.create_conversation()
    service.set_topic(conv.id, "Quantencomputing")
    loaded = service.load_conversation(conv.id)
    assert loaded.topic == "Quantencomputing"


# ── grant_floor / revoke_floor ────────────────────────────────────────────

def test_grant_floor_persists(service):
    conv = setup(service)
    service.grant_floor(conv.id, "p1")
    loaded = service.load_conversation(conv.id)
    assert loaded.floor == "p1"


def test_grant_floor_transfers_between_participants(service):
    conv = setup(service)
    service.grant_floor(conv.id, "p1")
    service.grant_floor(conv.id, "p2")
    loaded = service.load_conversation(conv.id)
    assert loaded.floor == "p2"


def test_revoke_floor_clears_floor(service):
    conv = setup(service)
    service.grant_floor(conv.id, "p1")
    service.revoke_floor(conv.id)
    loaded = service.load_conversation(conv.id)
    assert loaded.floor is None


def test_grant_floor_raises_for_unknown_participant(service):
    conv = service.create_conversation()
    with pytest.raises(ParticipantNotRegistered):
        service.grant_floor(conv.id, "unbekannt")


# ── invoke_with_floor ─────────────────────────────────────────────────────

def test_invoke_with_floor_calls_participant_with_floor(service):
    from conclave.application.adapter_registry import AdapterRegistry

    class FakeAdapter:
        provider = "test"
        def __init__(self): self.called = False
        def complete(self, conv, part): self.called = True; return "Antwort"

    adapter = FakeAdapter()
    registry = AdapterRegistry()
    registry.register("p1", adapter)
    service.set_adapter_registry(registry)

    conv = setup(service)
    service.add_user_message(conv.id, "Frage")
    service.grant_floor(conv.id, "p1")

    updated = service.invoke_with_floor(conv.id)

    assert adapter.called
    assert len(updated.messages) == 2
    assert updated.messages[1].content == "Antwort"
    assert updated.messages[1].author_id == "p1"


def test_invoke_with_floor_revokes_floor_after_response(service):
    from conclave.application.adapter_registry import AdapterRegistry

    registry = AdapterRegistry()
    registry.register("p1", type('A', (), {'complete': lambda s,c,p: 'ok'})())
    service.set_adapter_registry(registry)

    conv = setup(service)
    service.add_user_message(conv.id, "Frage")
    service.grant_floor(conv.id, "p1")
    service.invoke_with_floor(conv.id)

    loaded = service.load_conversation(conv.id)
    assert loaded.floor is None


def test_invoke_with_floor_raises_when_no_floor_set(service):
    conv = setup(service)
    service.add_user_message(conv.id, "Frage")
    with pytest.raises(NoFloorGranted):
        service.invoke_with_floor(conv.id)


def test_invoke_participant_respects_floor_when_floor_is_set(service):
    """invoke_participant ohne floor_check überspringt die Prüfung – bleibt kompatibel."""
    from conclave.application.adapter_registry import AdapterRegistry

    registry = AdapterRegistry()
    registry.register("p1", type('A', (), {'complete': lambda s,c,p: 'ok'})())
    service.set_adapter_registry(registry)

    conv = setup(service)
    service.add_user_message(conv.id, "Frage")
    # kein grant_floor – invoke_participant ohne floor-Prüfung sollte weiterhin funktionieren
    updated = service.invoke_participant(conv.id, "p1")
    assert len(updated.messages) == 2
