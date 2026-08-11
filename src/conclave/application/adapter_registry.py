# src/conclave/application/adapter_registry.py

from collections.abc import Callable

from conclave.application.ports import ModelAdapter
from conclave.domain.errors import AdapterNotFound


class AdapterRegistry:
    """Verknuepft Participant-IDs mit konkreten ModelAdapter-Implementierungen.

    Unterstuetzt zwei Modi:
    - Eager: adapter wird per register() vorregistriert (wie bisher)
    - Lazy: ein builder wird gesetzt und baut Adapter bei Bedarf aus der DB
    """

    def __init__(self):
        self._adapters: dict[str, ModelAdapter] = {}
        self._builder: Callable[[str], ModelAdapter | None] | None = None

    def set_builder(self, builder: Callable[[str], ModelAdapter | None]) -> None:
        """Setzt eine Builder-Funktion die Adapter on-demand aus der DB baut."""
        self._builder = builder

    def register(self, participant_id: str, adapter: ModelAdapter) -> None:
        self._adapters[participant_id] = adapter

    def invalidate(self, participant_id: str | None = None) -> None:
        """Entfernt gecachte Adapter. None = alle."""
        if participant_id:
            self._adapters.pop(participant_id, None)
        else:
            self._adapters.clear()

    def get_for(self, participant_id: str) -> ModelAdapter:
        adapter = self._adapters.get(participant_id)
        if adapter is None and self._builder:
            adapter = self._builder(participant_id)
            if adapter:
                self._adapters[participant_id] = adapter
        if adapter is None:
            raise AdapterNotFound(participant_id)
        return adapter
