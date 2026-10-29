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
from conclave.domain.board import Project, Task, TaskComment, TaskEvent
from conclave.domain.consultation import Consultation, ConsultationDelivery
from conclave.domain.context_report import ContextReportRecord
from conclave.domain.conversation import Conversation
from conclave.domain.message import Message
from conclave.domain.model_response import Completion
from conclave.domain.participant import Participant
from conclave.domain.run import Run
from conclave.domain.ticket import Ticket
from conclave.domain.tool_event import ToolEvent


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

    complete() liefert ein Completion (Text, Usage, Kontext-Report); einfache
    Adapter duerfen weiterhin nur den Text (str) liefern - dann ohne Usage.
    """

    @property
    def provider(self) -> str:
        """Provider-Name fuer Audit-Log (z.B. 'anthropic', 'openai', 'gemini')."""
        ...

    def complete(self, conversation: Conversation, participant: Participant) -> Completion | str:
        """Sendet die Conversation an den Provider und gibt die Antwort zurueck."""
        ...


@runtime_checkable
class StreamingModelAdapter(Protocol):
    """Erweiterung von ModelAdapter mit Token-Streaming."""

    @property
    def provider(self) -> str:
        """Provider-Name fuer Audit-Log."""
        ...

    def complete(self, conversation: Conversation, participant: Participant) -> Completion | str:
        """Nicht-streamende Variante — gibt die vollstaendige Antwort zurueck."""
        ...

    def stream(
        self, conversation: Conversation, participant: Participant
    ) -> Iterator[str | Completion]:
        """Streamt die Antwort Token fuer Token; zum Abschluss optional ein Completion ohne Text."""
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

    def list_by_conversation(self, conversation_id: str) -> list[AuditEntry]:
        """Gibt alle Audit-Eintraege einer Conversation zurueck."""
        ...

    def list_by_date_range(self, start: datetime, end: datetime) -> list[AuditEntry]:
        """Gibt Laufprotokoll-Eintraege in einem Zeitraum zurueck."""
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


@runtime_checkable
class ToolEventRepository(Protocol):
    """Persistiert deterministische Backend-Ereignisse aus Tool-Directives."""

    def save(self, event: ToolEvent) -> None:
        """Speichert ein Tool-Event."""
        ...

    def list_by_conversation(self, conversation_id: str) -> list[ToolEvent]:
        """Gibt alle Tool-Events einer Conversation zurueck."""
        ...

    def list_by_message(self, message_id: str) -> list[ToolEvent]:
        """Gibt alle Tool-Events einer Message zurueck."""
        ...


@runtime_checkable
class ContextReportRepository(Protocol):
    """Persistiert Kontext-Reports (welcher Kontext an den Provider ging)."""

    def save(self, record: ContextReportRecord) -> None:
        """Speichert einen Report."""
        ...

    def link_message(self, record_id: str, message_id: str) -> None:
        """Verknuepft einen gespeicherten Report nachtraeglich mit der Antwort."""
        ...

    def get_by_message(self, message_id: str) -> ContextReportRecord | None:
        """Report zu einer Modellantwort oder None."""
        ...

    def list_by_conversation(self, conversation_id: str) -> list[ContextReportRecord]:
        """Alle Reports einer Conversation (auch fehlgeschlagene Aufrufe)."""
        ...


@runtime_checkable
class ConsultationRepository(Protocol):
    """Persistiert Consultations und ihre Zustellungen."""

    def save(self, consultation: Consultation) -> None:
        """Speichert oder aktualisiert eine Consultation."""
        ...

    def get(self, consultation_id: str) -> Consultation | None:
        ...

    def list_by_source_ref(self, source: str, source_ref: str) -> list[Consultation]:
        """Consultations zu einem Ticket, neueste zuerst."""
        ...

    def list_by_status(self, status: str) -> list[Consultation]:
        """Consultations mit einem Status, aelteste zuerst."""
        ...

    def count_since(self, source: str, source_ref: str, since: datetime) -> int:
        """Anzahl der Consultations zu einem Ticket seit ``since`` (Obergrenze)."""
        ...

    def claim(self, consultation_id: str) -> bool:
        """Atomar queued -> running; True nur fuer genau einen Aufrufer."""
        ...

    def save_delivery(self, delivery: ConsultationDelivery) -> None:
        ...

    def list_deliveries(self, consultation_id: str) -> list[ConsultationDelivery]:
        ...


@runtime_checkable
class TaskSource(Protocol):
    """Liest Tickets aus einem externen Board (z. B. Kanzo). Inhalt ist fremd und unvertrauenswuerdig."""

    def get_task(self, task_ref: str) -> Ticket:
        """Laedt ein Ticket samt Kommentaren; wirft TaskNotFound oder TaskSourceError."""
        ...


@runtime_checkable
class CommentSink(Protocol):
    """Schreibt Kommentare in ein externes Board - die einzige schreibende Aktion dort."""

    def add_comment(self, task_ref: str, body: str, author: str) -> None:
        """Fuegt einen Kommentar hinzu; wirft TaskNotFound oder TaskSourceError."""
        ...


class BoardRepository(Protocol):
    """Speicher des Boards (B1). Regeln und Rechte liegen im BoardService (B2)."""

    def change_token(self) -> int:
        """Aenderungszaehler; steigt mit jeder Schreiboperation."""
        ...

    def create_project(self, project: Project) -> None: ...
    def get_project(self, slug: str) -> Project | None: ...
    def list_projects(self) -> list[Project]: ...
    def rename_project(self, slug: str, name: str) -> bool: ...
    def delete_project(self, slug: str) -> bool: ...

    def create_task(self, task: Task) -> Task:
        """Legt das Ticket an und vergibt die naechste Nummer des Projekts (atomar)."""
        ...

    def get_task(self, slug: str, number: int) -> Task | None: ...
    def get_task_by_id(self, task_id: str) -> Task | None: ...
    def list_tasks(self, slug: str | None = None, statuses=None) -> list[Task]: ...
    def update_task(self, task: Task, events=()) -> bool:
        """Ticket und Verlaufseintraege zusammen (atomar)."""
        ...

    def claim_task(self, task_id: str, from_status: str, to_status: str, position: float, updated_at,
                   event: TaskEvent | None = None) -> bool:
        """Verschiebt nur, wenn das Ticket noch in ``from_status`` steht; Verlauf im selben Schritt."""
        ...

    def delete_task(self, task_id: str) -> bool: ...
    def column_positions(self, project_id: str, status: str) -> list[tuple[str, float]]: ...
    def renumber_column(self, project_id: str, status: str) -> None: ...

    def add_comment(self, comment: TaskComment, *, only_if_not_human: bool = False) -> bool: ...

    def add_comment_checked(self, comment: TaskComment, *, only_if_not_human: bool = False) -> bool:
        """Wie add_comment, aber ``False`` statt Ausnahme, wenn nicht geschrieben (fehlt/markiert)."""
        ...
    def get_comment(self, comment_id: str) -> TaskComment | None: ...
    def list_comments(self, task_id: str) -> list[TaskComment]: ...
    def update_comment(self, comment: TaskComment) -> bool: ...
    def delete_comment(self, comment_id: str) -> bool: ...

    def add_event(self, event: TaskEvent) -> None: ...
    def list_events(self, task_id: str) -> list[TaskEvent]: ...


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
