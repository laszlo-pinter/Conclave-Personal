# src/conclave/application/ports.py
"""Ports (Interfaces) — Definiert die Grenzen zwischen Application und Infrastructure.

Alle Ports sind als typing.Protocol mit @runtime_checkable implementiert.
Infrastructure-Adapter implementieren diese Protocols implizit (strukturelles Subtyping).
"""

from collections.abc import AsyncIterator, Iterator
from typing import Protocol, runtime_checkable

from datetime import datetime

from conclave.domain.agent import Agent
from conclave.domain.audit import AuditEntry
from conclave.domain.conversation import Conversation
from conclave.domain.message import Message
from conclave.domain.participant import Participant
from conclave.domain.run import Run


@runtime_checkable
class AgentRepository(Protocol):
    """Persistiert Agent-Konfigurationen (Provider, Model, API-Key, Presets)."""

    def save(self, agent: Agent) -> None:
        """Speichert oder aktualisiert einen Agent."""
        ...

    def get(self, agent_id: str) -> Agent | None:
        """Laedt einen Agent oder gibt None zurueck."""
        ...

    def list_all(self) -> list[Agent]:
        """Gibt alle registrierten Agents zurueck."""
        ...

    def delete(self, agent_id: str) -> None:
        """Loescht einen Agent."""
        ...


@runtime_checkable
class ModelAdapter(Protocol):
    """Outbound-Port: Conclave ruft das Modell auf, nie umgekehrt.

    Jeder LLM-Provider (Anthropic, OpenAI, Gemini, ...) implementiert
    dieses Interface. Der Adapter erhaelt die gesamte Conversation und
    den Participant fuer den er antwortet.
    """

    @property
    def provider(self) -> str:
        """Provider-Name fuer Audit-Log (z.B. 'anthropic', 'openai', 'gemini')."""
        ...

    def complete(self, conversation: Conversation, participant: Participant) -> str:
        """Sendet die Conversation an den Provider und gibt die Antwort zurueck."""
        ...


@runtime_checkable
class StreamingModelAdapter(Protocol):
    """Erweiterung von ModelAdapter mit Token-Streaming."""

    @property
    def provider(self) -> str:
        """Provider-Name fuer Audit-Log."""
        ...

    def complete(self, conversation: Conversation, participant: Participant) -> str:
        """Nicht-streamende Variante — gibt die vollstaendige Antwort zurueck."""
        ...

    def stream(
        self, conversation: Conversation, participant: Participant
    ) -> Iterator[str]:
        """Streamt die Antwort Token fuer Token als Iterator."""
        ...


@runtime_checkable
class AsyncModelAdapter(Protocol):
    """Async-Variante von ModelAdapter fuer parallele Orchestrierung."""

    @property
    def provider(self) -> str:
        """Provider-Name fuer Audit-Log."""
        ...

    async def complete(self, conversation: Conversation, participant: Participant) -> str:
        """Async: Sendet die Conversation und gibt die Antwort zurueck."""
        ...


@runtime_checkable
class AsyncStreamingModelAdapter(Protocol):
    """Async-Variante von StreamingModelAdapter mit AsyncIterator."""

    @property
    def provider(self) -> str:
        """Provider-Name fuer Audit-Log."""
        ...

    async def complete(self, conversation: Conversation, participant: Participant) -> str:
        """Async: Gibt die vollstaendige Antwort zurueck."""
        ...

    def stream(
        self, conversation: Conversation, participant: Participant
    ) -> AsyncIterator[str]:
        """Async: Streamt die Antwort Token fuer Token."""
        ...


@runtime_checkable
class ConversationRepository(Protocol):
    """Persistiert Conversations mit Participants (Messages separat)."""

    def save(self, conversation: Conversation) -> None:
        """Speichert oder aktualisiert eine Conversation (Upsert)."""
        ...

    def load(self, conversation_id: str) -> Conversation | None:
        """Laedt eine Conversation inkl. Participants. Messages werden separat geladen."""
        ...

    def list_all(self) -> list[Conversation]:
        """Gibt alle Conversations zurueck (ohne Messages)."""
        ...

    def delete(self, conversation_id: str) -> None:
        """Loescht eine Conversation inkl. zugehoeriger Messages und Participants."""
        ...


@runtime_checkable
class MessageRepository(Protocol):
    """Persistiert Messages. Unterstuetzt optionale Verschluesselung (CryptoService)."""

    def save(self, message: Message) -> None:
        """Speichert eine Message. Sequence wird atomar aus der DB berechnet."""
        ...

    def list_by_conversation_id(self, conversation_id: str) -> list[Message]:
        """Gibt alle Messages einer Conversation zurueck, sortiert nach Sequence."""
        ...


@runtime_checkable
class ParticipantRepository(Protocol):
    """Persistiert Conversation-Participants (Model oder User)."""

    def save(self, participant: Participant) -> None:
        """Speichert einen Participant."""
        ...

    def list_by_conversation_id(self, conversation_id: str) -> list[Participant]:
        """Gibt alle Participants einer Conversation zurueck."""
        ...

    def delete_by_conversation(self, conversation_id: str) -> None:
        """Loescht alle Participants einer Conversation."""
        ...

    def delete(self, conversation_id: str, participant_id: str) -> None:
        """Loescht einen Participant aus einer Conversation."""
        ...


@runtime_checkable
class AuditRepository(Protocol):
    """Persistiert Laufprotokoll-Eintraege fuer Provider-Aufrufe."""

    def save(self, entry: AuditEntry) -> None:
        """Speichert einen Audit-Eintrag (Provider-Call, Fehler, Token-Verbrauch)."""
        ...


@runtime_checkable
class RunRepository(Protocol):
    """Persistiert Personal-Runs und optionale Usage-Daten."""

    def save(self, run: Run) -> None:
        """Speichert oder aktualisiert einen Run."""
        ...

    def get(self, run_id: str) -> Run | None:
        """Laedt einen Run oder gibt None zurueck."""
        ...

    def list_all(self, limit: int = 100) -> list[Run]:
        """Gibt Runs absteigend nach Startzeit zurueck."""
        ...

    def list_by_conversation(self, conversation_id: str, limit: int = 100) -> list[Run]:
        """Gibt Runs einer Conversation absteigend nach Startzeit zurueck."""
        ...

    def list_by_conversation(self, conversation_id: str) -> list[AuditEntry]:
        """Gibt alle Audit-Eintraege einer Conversation zurueck."""
        ...

    def list_by_date_range(self, start: datetime, end: datetime) -> list[AuditEntry]:
        """Gibt Laufprotokoll-Eintraege in einem Zeitraum zurueck."""
        ...


@runtime_checkable
class UnitOfWork(Protocol):
    """Transaktionsgrenze — steuert Commit und Rollback fuer alle Repositories."""

    conversations: ConversationRepository
    messages: MessageRepository
    participants: ParticipantRepository

    def __enter__(self) -> "UnitOfWork":
        """Startet eine Transaktion."""
        ...

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Commit bei Erfolg, Rollback bei Exception."""
        ...
