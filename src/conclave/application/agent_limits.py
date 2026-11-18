"""Grenzen fuer Modelllaeufe von Agenten (R11): Tagesbudget, Budget je Conversation, gleichzeitige Laeufe.

Ein ``AgentRunGate`` gilt fuer den ganzen Server: Die API (Invoke, Orchestrate) und der
Consultation-Worker nutzen dieselbe Instanz, zaehlen also gegen dasselbe Budget und dieselbe
Zahl gleichzeitiger Laeufe. Geprueft wird dort, wo der Modellaufruf beginnt; Laeufe innerhalb
von ``agent_run`` tragen die Herkunft ``agent`` (``RUN_ORIGIN``) und zaehlen so ins Budget.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from conclave.application.conversation_flow import RUN_ORIGIN
from conclave.domain.errors import ConclaveError


class AgentLimitExceeded(ConclaveError):
    """Eine Grenze fuer Agenten ist erreicht; ``type`` ist der Fehlertyp fuer Clients (HTTP 429)."""

    def __init__(self, message: str, error_type: str) -> None:
        self.type = error_type
        super().__init__(message)


class AgentRunGate:
    def __init__(self, limits, run_repo: Callable[[], object | None] = lambda: None) -> None:
        self._limits = limits
        self._run_repo = run_repo                 # spaet gebunden: das Repository kommt nach dem Dienst
        self._lock = threading.Lock()
        self._active = 0

    @property
    def active(self) -> int:
        return self._active

    def check_budget(self, conversation_id: str | None = None) -> None:
        repo = self._run_repo()
        if repo is None:
            return
        since = datetime.now(timezone.utc) - timedelta(days=1)
        limits = self._limits
        if limits.agent_tokens_per_day:
            used = repo.tokens_since(since, origin="agent")
            if used >= limits.agent_tokens_per_day:
                raise AgentLimitExceeded(
                    f"Tagesbudget der Agenten erschoepft: {used} von {limits.agent_tokens_per_day} Tokens in den "
                    "letzten 24 Stunden ([limits] agent_tokens_per_day).", "AgentBudgetExceeded")
        if limits.conversation_tokens_per_day and conversation_id:
            used = repo.tokens_since(since, origin="agent", conversation_id=conversation_id)
            if used >= limits.conversation_tokens_per_day:
                raise AgentLimitExceeded(
                    f"Budget dieser Conversation fuer Agenten erschoepft: {used} von "
                    f"{limits.conversation_tokens_per_day} Tokens in den letzten 24 Stunden "
                    "([limits] conversation_tokens_per_day).", "ConversationBudgetExceeded")

    def acquire(self) -> bool:
        """Einen Platz fuer einen Lauf belegen; False, wenn es keine Grenze gibt (nichts freizugeben)."""
        if not self._limits.agent_concurrent_runs:
            return False
        with self._lock:
            if self._active >= self._limits.agent_concurrent_runs:
                raise AgentLimitExceeded(
                    f"Zu viele gleichzeitige Modelllaeufe von Agenten (hoechstens "
                    f"{self._limits.agent_concurrent_runs}, [limits] agent_concurrent_runs).", "TooManyAgentRuns")
            self._active += 1
        return True

    def release(self) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)

    @contextmanager
    def agent_run(self, conversation_id: str | None = None) -> Iterator[None]:
        """Budget pruefen, Platz belegen, Laeufe als ``agent`` kennzeichnen - fuer die Dauer des Blocks."""
        self.check_budget(conversation_id)
        held = self.acquire()
        token = RUN_ORIGIN.set("agent")
        try:
            yield
        finally:
            RUN_ORIGIN.reset(token)
            if held:
                self.release()
