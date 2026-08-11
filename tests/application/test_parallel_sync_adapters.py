# tests/application/test_parallel_sync_adapters.py
"""Regression: ParallelOrchestrator muss auch mit SYNC-Adaptern wirklich
blind-parallel sein - kein Adapter darf in seinem Snapshot die Antworten
anderer Adapter aus derselben Gruppe sehen.

Hintergrund: Production-Adapter (anthropic, openai, universal, resilient)
sind alle sync. Bevor asyncio.to_thread in async_invoke_participant
eingezogen wurde, hat ein sync-Adapter die Event-Loop blockiert -> der
naechste Adapter in derselben Gruppe sah die Antwort des Ersten."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock

import pytest

from conclave.application.adapter_registry import AdapterRegistry
from conclave.application.orchestrator import ParallelOrchestrator
from conclave.domain.participant import ParticipantType


def _make_sync_adapter(name: str, captured: dict, sleep_s: float = 0.0):
    """Sync-Adapter (wie Production), der den Snapshot zum Zeitpunkt des Calls capturet."""
    adapter = MagicMock()
    adapter.provider = "test"
    adapter._model = "test"
    adapter.last_usage = None

    def complete(snapshot, participant):
        if sleep_s:
            time.sleep(sleep_s)
        captured[name] = [m.content for m in snapshot.messages]
        return f"{name}_response"

    adapter.complete = complete
    return adapter


@pytest.mark.asyncio
async def test_sync_adapters_in_one_group_are_blind_parallel(service):
    """Beide sync-Adapter in derselben Gruppe MUESSEN den gleichen Snapshot sehen."""
    conv = service.create_conversation()
    service.register_participant(conv.id, "A", ParticipantType.MODEL, "A")
    service.register_participant(conv.id, "B", ParticipantType.MODEL, "B")
    service.add_user_message(conv.id, "START")

    captured: dict[str, list[str]] = {}
    registry = AdapterRegistry()
    # A bekommt eine kuenstliche Verzoegerung, sodass B beim Snapshot-Lesen
    # waehrend A noch laeuft NICHT die persistierte A-Antwort sehen darf.
    registry.register("A", _make_sync_adapter("A", captured, sleep_s=0.3))
    registry.register("B", _make_sync_adapter("B", captured))
    service.set_adapter_registry(registry)

    orchestrator = ParallelOrchestrator(service)
    result = await orchestrator.run(conv.id, groups=[["A", "B"]])

    assert result.success
    assert captured["A"] == ["START"], f"A sah {captured['A']}"
    assert captured["B"] == ["START"], (
        f"B sah {captured['B']} - sollte 'START' allein sein (blind-parallel). "
        "Wenn 'A_response' drin ist, blockiert der sync-Adapter die Event-Loop."
    )


@pytest.mark.asyncio
async def test_later_group_sees_earlier_group_responses(service):
    """Cross-Group bleibt sequenziell: Gruppe 2 SIEHT Antworten von Gruppe 1."""
    conv = service.create_conversation()
    for pid in ["A", "B", "C"]:
        service.register_participant(conv.id, pid, ParticipantType.MODEL, pid)
    service.add_user_message(conv.id, "START")

    captured: dict[str, list[str]] = {}
    registry = AdapterRegistry()
    for pid in ["A", "B", "C"]:
        registry.register(pid, _make_sync_adapter(pid, captured))
    service.set_adapter_registry(registry)

    orchestrator = ParallelOrchestrator(service)
    result = await orchestrator.run(conv.id, groups=[["A", "B"], ["C"]])

    assert result.success
    # Gruppe 1: blind-parallel
    assert captured["A"] == ["START"]
    assert captured["B"] == ["START"]
    # Gruppe 2: sieht Antworten von Gruppe 1
    assert "A_response" in captured["C"]
    assert "B_response" in captured["C"]


@pytest.mark.asyncio
async def test_parallel_actually_runs_concurrently_with_sync_adapters(service):
    """Wenn beide sync-Adapter je 0.5s schlafen, darf die Gruppe nicht 1.0s+
    brauchen sondern nur ~0.5s (echte Parallelitaet via to_thread)."""
    conv = service.create_conversation()
    service.register_participant(conv.id, "A", ParticipantType.MODEL, "A")
    service.register_participant(conv.id, "B", ParticipantType.MODEL, "B")
    service.add_user_message(conv.id, "START")

    captured: dict[str, list[str]] = {}
    registry = AdapterRegistry()
    registry.register("A", _make_sync_adapter("A", captured, sleep_s=0.5))
    registry.register("B", _make_sync_adapter("B", captured, sleep_s=0.5))
    service.set_adapter_registry(registry)

    orchestrator = ParallelOrchestrator(service)
    t0 = time.monotonic()
    await orchestrator.run(conv.id, groups=[["A", "B"]])
    elapsed = time.monotonic() - t0

    # Sequenziell waeren es 1.0s; parallel ~0.5s. Toleranz fuer Test-Overhead.
    assert elapsed < 0.9, f"Gruppe brauchte {elapsed:.2f}s - vermutlich blockierender sync-Call"
