# tests/application/test_adapter_registry.py

import pytest

from conclave.application.adapter_registry import AdapterRegistry
from conclave.application.ports import ModelAdapter
from conclave.domain.conversation import Conversation
from conclave.domain.participant import Participant, ParticipantType
from conclave.domain.errors import AdapterNotFound


class FakeAdapter:
    provider = "test"
    def complete(self, conversation: Conversation, participant: Participant) -> str:
        return "ok"


def test_registered_adapter_can_be_retrieved():
    registry = AdapterRegistry()
    adapter = FakeAdapter()

    registry.register("p1", adapter)

    assert registry.get_for("p1") is adapter


def test_get_for_unknown_participant_raises():
    registry = AdapterRegistry()

    with pytest.raises(AdapterNotFound):
        registry.get_for("unbekannt")


def test_adapter_not_found_error_contains_participant_id():
    registry = AdapterRegistry()

    with pytest.raises(AdapterNotFound) as exc_info:
        registry.get_for("p-xyz")

    assert "p-xyz" in str(exc_info.value)


def test_registered_adapter_satisfies_protocol():
    registry = AdapterRegistry()
    adapter = FakeAdapter()
    registry.register("p1", adapter)

    result = registry.get_for("p1")
    assert isinstance(result, ModelAdapter)


def test_second_registration_overwrites_first():
    registry = AdapterRegistry()
    adapter_a = FakeAdapter()
    adapter_b = FakeAdapter()

    registry.register("p1", adapter_a)
    registry.register("p1", adapter_b)

    assert registry.get_for("p1") is adapter_b


def test_registry_isolates_different_participants():
    registry = AdapterRegistry()
    adapter_a = FakeAdapter()
    adapter_b = FakeAdapter()

    registry.register("p1", adapter_a)
    registry.register("p2", adapter_b)

    assert registry.get_for("p1") is adapter_a
    assert registry.get_for("p2") is adapter_b


def test_lazy_builder_creates_adapter_on_demand():
    registry = AdapterRegistry()
    built = FakeAdapter()
    registry.set_builder(lambda pid: built if pid == "lazy-1" else None)

    assert registry.get_for("lazy-1") is built


def test_lazy_builder_caches_after_first_build():
    call_count = 0
    def builder(pid):
        nonlocal call_count
        call_count += 1
        return FakeAdapter()

    registry = AdapterRegistry()
    registry.set_builder(builder)

    registry.get_for("p1")
    registry.get_for("p1")
    assert call_count == 1


def test_lazy_builder_raises_if_returns_none():
    registry = AdapterRegistry()
    registry.set_builder(lambda pid: None)

    with pytest.raises(AdapterNotFound):
        registry.get_for("unknown")


def test_invalidate_clears_cache_forces_rebuild():
    call_count = 0
    def builder(pid):
        nonlocal call_count
        call_count += 1
        return FakeAdapter()

    registry = AdapterRegistry()
    registry.set_builder(builder)

    registry.get_for("p1")
    assert call_count == 1

    registry.invalidate("p1")
    registry.get_for("p1")
    assert call_count == 2


def test_invalidate_all_clears_entire_cache():
    registry = AdapterRegistry()
    registry.register("p1", FakeAdapter())
    registry.register("p2", FakeAdapter())
    registry.set_builder(lambda pid: None)

    registry.invalidate()

    with pytest.raises(AdapterNotFound):
        registry.get_for("p1")
