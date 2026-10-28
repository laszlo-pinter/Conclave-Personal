from collections.abc import AsyncIterator, Iterator

import asyncio
import dataclasses
import inspect
import os
import re

import uuid
from datetime import datetime, timezone

from conclave.application.adapter_registry import AdapterRegistry
from conclave.application.participant_service import ParticipantService
from conclave.application.ports import AuditRepository, ContextReportRepository, ConversationRepository, MessageRepository, ModelAdapter, ParticipantRepository, RunRepository, StreamingModelAdapter, ToolEventRepository
from conclave.application.workspace_security import (
    agent_read_limit_bytes,
    assert_size_allowed,
    is_agent_visible,
    resolve_output_path,
    resolve_workspace_path,
    workspace_root,
    write_limit_bytes,
)
from conclave.domain.audit import AuditEntry
from conclave.domain.context_report import ContextReport, ContextReportRecord
from conclave.domain.conversation import Conversation
from conclave.domain.errors import (
    AdapterNotFound,
    ConversationNotFound,
    EmptyConversation,
    NoFloorGranted,
    ParticipantNotRegistered,
)
from conclave.domain.model_response import Completion, completion_text
from conclave.domain.participant import ParticipantType
from conclave.domain.run import Run, UsageRecord
from conclave.domain.tool_event import ToolEvent
from conclave.infrastructure.log import get_logger, request_logger

logger = get_logger("application.conversation_flow")


@dataclasses.dataclass(frozen=True)
class AgentTurn:
    """Noch nicht gespeicherte Agent-Antwort mit der ID ihres Kontext-Reports."""
    text: str
    context_report_id: str | None = None


def _report_from_exception(exc: BaseException) -> ContextReport | None:
    """Report einer fehlgeschlagenen Anfrage - auch aus der Ursache (raise ... from exc)."""
    seen = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        report = getattr(current, "context_report", None)
        if isinstance(report, ContextReport):
            return report
        current = current.__cause__ or current.__context__
    return None


class ConversationFlowService:
    def __init__(
        self,
        conversation_repository: ConversationRepository,
        message_repository: MessageRepository,
        participant_repository: ParticipantRepository,
    ):
        self._conversation_repository = conversation_repository
        self._message_repository = message_repository
        self._participant_repository = participant_repository
        self._participant_service = ParticipantService(conversation_repository, participant_repository)
        self._registry: AdapterRegistry | None = None
        self._audit_repo: AuditRepository | None = None
        self._run_repo: RunRepository | None = None
        self._tool_event_repo: ToolEventRepository | None = None
        self._context_report_repo: ContextReportRepository | None = None

    def set_adapter_registry(self, registry: AdapterRegistry) -> None:
        self._registry = registry

    def set_audit_repository(self, audit_repo: AuditRepository) -> None:
        self._audit_repo = audit_repo

    def set_run_repository(self, run_repo: RunRepository) -> None:
        self._run_repo = run_repo

    def set_tool_event_repository(self, tool_event_repo: ToolEventRepository) -> None:
        self._tool_event_repo = tool_event_repo

    def set_context_report_repository(self, repo: ContextReportRepository) -> None:
        self._context_report_repo = repo

    def _save_context_report(
        self,
        conversation_id: str,
        participant_id: str,
        source,
        run_id: str | None,
        message_id: str | None = None,
    ) -> str | None:
        """Speichert den Report eines Aufrufs; source ist ein Completion oder die Exception.

        Fehler beim Speichern brechen den Aufruf nie ab - der Report ist Zusatzinformation.
        """
        if self._context_report_repo is None:
            return None
        if isinstance(source, BaseException):
            report, usage = _report_from_exception(source), None
        else:
            report = source.report if isinstance(source, Completion) else None
            usage = source.usage if isinstance(source, Completion) else None
        if report is None:
            return None
        record = ContextReportRecord.create(
            conversation_id=conversation_id,
            participant_id=participant_id,
            report=report,
            run_id=run_id,
            message_id=message_id,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )
        try:
            self._context_report_repo.save(record)
        except Exception:
            logger.exception("Kontext-Report konnte nicht gespeichert werden",
                             extra={"conversation_id": conversation_id, "participant_id": participant_id})
            return None
        return record.id

    def get_context_report_for_message(self, message_id: str) -> ContextReportRecord | None:
        if self._context_report_repo is None:
            return None
        return self._context_report_repo.get_by_message(message_id)

    def list_context_reports(self, conversation_id: str) -> list[ContextReportRecord]:
        if self._context_report_repo is None:
            return []
        return self._context_report_repo.list_by_conversation(conversation_id)

    def preview_context(self, conversation_id: str, participant_id: str) -> ContextReport | None:
        """Was der naechste Aufruf senden wuerde - ohne Provider-Aufruf.

        None, wenn der Adapter keine Vorschau anbietet.
        """
        conversation = self.load_conversation(conversation_id)
        participant = next((p for p in conversation.participants if p.id == participant_id), None)
        if participant is None:
            raise ParticipantNotRegistered(participant_id=participant_id, conversation_id=conversation_id)
        if self._registry is None:
            raise AdapterNotFound(participant_id)
        adapter = self._registry.get_for(participant_id)
        preview = getattr(type(adapter), "context_report", None)
        if not callable(preview):
            return None
        snapshot = dataclasses.replace(conversation, messages=list(conversation.messages))
        snapshot = self._expand_workspace_refs(snapshot)
        return preview(adapter, snapshot, participant)

    @staticmethod
    def _ensure_has_messages(conversation: Conversation) -> None:
        if not conversation.messages:
            raise EmptyConversation(conversation.id)

    def _audit(
        self,
        operation: str,
        conversation_id: str,
        participant_id: str,
        provider: str = "",
        model: str = "",
        success: bool = True,
        error_message: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        if self._audit_repo is None:
            return
        entry = AuditEntry(
            id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc),
            operation=operation,
            conversation_id=conversation_id,
            participant_id=participant_id,
            provider=provider,
            model=model,
            success=success,
            error_message=error_message,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        self._audit_repo.save(entry)

    def _record_run(
        self,
        kind: str,
        conversation_id: str,
        participants: list[str],
        started_at: datetime,
        status: str,
        provider: str = "",
        model: str = "",
        error: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> str | None:
        if self._run_repo is None:
            return None
        usage = None
        if provider or model or input_tokens is not None or output_tokens is not None:
            usage = UsageRecord(
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        run = Run(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            kind=kind,
            participants=participants,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            status=status,
            error=error,
            usage=usage,
        )
        self._run_repo.save(run)
        return run.id

    @staticmethod
    def _usage_tokens(result) -> tuple[int | None, int | None]:
        """Token aus dem Rueckgabewert des Adapters (Completion); str liefert keine."""
        usage = result.usage if isinstance(result, Completion) else None
        if usage is None:
            return None, None
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        return (
            input_tokens if isinstance(input_tokens, int) else None,
            output_tokens if isinstance(output_tokens, int) else None,
        )

    @staticmethod
    def _expand_workspace_refs(conversation: Conversation) -> Conversation:
        """Expandiert @workspace/datei.md Referenzen in Messages.

        Ersetzt @workspace/pfad durch den Dateiinhalt. Unlesbare oder
        fehlende Dateien werden mit Fehlermeldung ersetzt.
        """
        pattern = re.compile(r'@work(?:space|place)/([\w./-]+)')
        limit = agent_read_limit_bytes()
        changed = False
        new_messages = []
        for msg in conversation.messages:
            matches = list(pattern.finditer(msg.content))
            if not matches:
                new_messages.append(msg)
                continue
            content = msg.content
            for match in matches:
                filepath = match.group(1)
                suffix = ""
                stripped_filepath = filepath.rstrip(".,;:!?")
                if stripped_filepath != filepath:
                    suffix = filepath[len(stripped_filepath):]
                    filepath = stripped_filepath
                original = match.group(0)
                resolved = resolve_workspace_path(filepath)
                if resolved is None:
                    content = content.replace(original, f"[FEHLER: Pfad nicht erlaubt]{suffix}")
                    continue
                if not is_agent_visible(resolved.path, root=resolved.root):
                    content = content.replace(original, f"[FEHLER: {filepath} nicht gefunden]{suffix}")
                    continue
                if resolved.path.is_file():
                    if not assert_size_allowed(resolved.path, limit):
                        content = content.replace(original, f"[FEHLER: {filepath} ist zu gross]{suffix}")
                        continue
                    try:
                        with open(resolved.path, "r", encoding="utf-8") as f:
                            file_content = f.read()
                        content = content.replace(
                            original,
                            f"\n--- Datei: {filepath} ---\n```\n{file_content}\n```\n{suffix}"
                        )
                    except Exception:
                        content = content.replace(original, f"[FEHLER: {filepath} nicht lesbar]{suffix}")
                else:
                    content = content.replace(original, f"[FEHLER: {filepath} nicht gefunden]{suffix}")
            replaced = dataclasses.replace(msg, content=content)
            new_messages.append(replaced)
            changed = True
        if changed:
            return dataclasses.replace(conversation, messages=new_messages)
        return conversation

    @staticmethod
    def _process_agent_directives(content: str) -> str:
        """Verarbeitet @save() und @read() Direktiven in Agent-Antworten.

        @save(datei)...@endsave — speichert Inhalt in workspace/output/
        @read(pfad) — wird durch den Dateiinhalt aus dem Workspace ersetzt
        """
        processed, _ = ConversationFlowService._process_agent_directives_for_context(
            content=content,
            conversation_id="",
            participant_id="",
            emit_tool_events=False,
        )
        return processed

    @staticmethod
    def _process_agent_directives_for_context(
        *,
        content: str,
        conversation_id: str,
        participant_id: str,
        emit_tool_events: bool,
    ) -> tuple[str, list[ToolEvent]]:
        """Verarbeitet Agent-Directives und gibt optionale Backend-Events zurueck."""
        root = workspace_root()
        events: list[ToolEvent] = []

        # @save(datei)...\n@endsave
        save_pattern = re.compile(
            r'@save\(([^)]+)\)\s*\n(.*?)(?:@endsave|$)',
            re.DOTALL,
        )
        def _save_replace(match):
            filepath = match.group(1).strip()
            file_content = match.group(2).strip()
            input_json = {
                "path": filepath,
                "content_bytes": len(file_content.encode("utf-8")),
            }

            def _legacy_or_event(
                *,
                status: str,
                legacy_text: str,
                output_json: dict | None = None,
                error: str | None = None,
            ) -> str:
                if not emit_tool_events:
                    return legacy_text
                event = ToolEvent.create(
                    conversation_id=conversation_id,
                    participant_id=participant_id,
                    tool="workspace.save",
                    status=status,
                    input_json=input_json,
                    output_json=output_json,
                    error=error,
                )
                events.append(event)
                return f"[tool_event:{event.id}]"

            resolved = resolve_output_path(filepath, root=root)
            if resolved is None:
                return _legacy_or_event(
                    status="failed",
                    legacy_text=f"[FEHLER: Pfad '{filepath}' nicht erlaubt]",
                    error="path_not_allowed",
                )
            content_bytes = len(file_content.encode("utf-8"))
            if content_bytes > write_limit_bytes():
                return _legacy_or_event(
                    status="failed",
                    legacy_text=f"[FEHLER: Datei '{filepath}' ist zu gross]",
                    output_json={"path": resolved.relative},
                    error="file_too_large",
                )
            try:
                os.makedirs(os.path.dirname(resolved.path), exist_ok=True)
                with open(resolved.path, "w", encoding="utf-8") as f:
                    f.write(file_content)
                return _legacy_or_event(
                    status="succeeded",
                    legacy_text=f"[Datei gespeichert: @workspace/output/{filepath}]",
                    output_json={
                        "path": resolved.relative,
                        "bytes_written": content_bytes,
                    },
                )
            except Exception as e:
                return _legacy_or_event(
                    status="failed",
                    legacy_text=f"[FEHLER beim Speichern von '{filepath}': {e}]",
                    output_json={"path": resolved.relative},
                    error=type(e).__name__,
                )
        content = save_pattern.sub(_save_replace, content)

        # @read(pfad)
        read_pattern = re.compile(r'@read\(([^)]+)\)')
        def _read_replace(match):
            filepath = match.group(1).strip()
            input_json = {"path": filepath}

            def _legacy_or_event(
                *,
                status: str,
                legacy_text: str,
                output_json: dict | None = None,
                error: str | None = None,
            ) -> str:
                if not emit_tool_events:
                    return legacy_text
                event = ToolEvent.create(
                    conversation_id=conversation_id,
                    participant_id=participant_id,
                    tool="workspace.read",
                    status=status,
                    input_json=input_json,
                    output_json=output_json,
                    error=error,
                )
                events.append(event)
                return f"[tool_event:{event.id}]\n{legacy_text}"

            resolved = resolve_workspace_path(filepath, root=root)
            if resolved is None:
                return _legacy_or_event(
                    status="failed",
                    legacy_text=f"[FEHLER: Pfad '{filepath}' nicht erlaubt]",
                    error="path_not_allowed",
                )
            if not is_agent_visible(resolved.path, root=root) or not resolved.path.is_file():
                return _legacy_or_event(
                    status="failed",
                    legacy_text=f"[FEHLER: {filepath} nicht gefunden]",
                    output_json={"path": resolved.relative},
                    error="file_not_found",
                )
            if not assert_size_allowed(resolved.path, agent_read_limit_bytes()):
                return _legacy_or_event(
                    status="failed",
                    legacy_text=f"[FEHLER: {filepath} ist zu gross]",
                    output_json={"path": resolved.relative},
                    error="file_too_large",
                )
            try:
                with open(resolved.path, "r", encoding="utf-8") as f:
                    file_content = f.read()
                return _legacy_or_event(
                    status="succeeded",
                    legacy_text=f"\n--- Datei: {filepath} ---\n```\n{file_content}\n```\n",
                    output_json={
                        "path": resolved.relative,
                        "bytes_read": len(file_content.encode("utf-8")),
                    },
                )
            except Exception as e:
                return _legacy_or_event(
                    status="failed",
                    legacy_text=f"[FEHLER: {filepath} nicht lesbar]",
                    output_json={"path": resolved.relative},
                    error=type(e).__name__,
                )
        content = read_pattern.sub(_read_replace, content)

        return content, events

    def _process_agent_response(
        self,
        *,
        content: str,
        conversation_id: str,
        participant_id: str,
    ) -> tuple[str, list[ToolEvent]]:
        return self._process_agent_directives_for_context(
            content=content,
            conversation_id=conversation_id,
            participant_id=participant_id,
            emit_tool_events=self._tool_event_repo is not None,
        )

    def _save_tool_events(self, events: list[ToolEvent], message_id: str) -> None:
        if self._tool_event_repo is None:
            return
        for event in events:
            event.message_id = message_id
            self._tool_event_repo.save(event)
            tool_path = ""
            if isinstance(event.output_json, dict):
                tool_path = str(event.output_json.get("path") or "")
            if not tool_path and isinstance(event.input_json, dict):
                tool_path = str(event.input_json.get("path") or "")
            logger.info(
                "tool_event recorded: %s %s",
                event.tool,
                event.status,
                extra={
                    "operation": "tool_event.record",
                    "conversation_id": event.conversation_id,
                    "participant_id": event.participant_id,
                    "message_id": message_id,
                    "run_id": event.run_id,
                    "tool_event_id": event.id,
                    "tool": event.tool,
                    "tool_path": tool_path,
                    "status": event.status,
                    "error": event.error,
                },
            )

    def _store_model_response(
        self,
        conversation: Conversation,
        participant_id: str,
        content: str,
        process_directives: bool = True,
    ):
        if process_directives:
            processed, events = self._process_agent_response(
                content=content,
                conversation_id=conversation.id,
                participant_id=participant_id,
            )
        else:
            # Consultations: @save/@read in Modellantworten bleiben Text (Injection ueber Tickets)
            processed, events = content, []
        message = conversation.add_model_message(
            participant_id=participant_id,
            content=processed,
        )
        self._message_repository.save(message)
        self._save_tool_events(events, message.id)
        return message

    def create_conversation(self, topic: str = "") -> Conversation:
        conversation = Conversation.create(topic=topic)
        self._conversation_repository.save(conversation)
        return conversation

    def set_topic(self, conversation_id: str, topic: str) -> Conversation:
        conversation = self.load_conversation(conversation_id)
        conversation.topic = topic
        self._conversation_repository.save(conversation)
        return conversation

    def set_rules(self, conversation_id: str, rules: str) -> Conversation:
        conversation = self.load_conversation(conversation_id)
        conversation.rules = rules
        self._conversation_repository.save(conversation)
        return conversation

    def grant_floor(self, conversation_id: str, participant_id: str) -> Conversation:
        conversation = self.load_conversation(conversation_id)
        conversation.grant_floor(participant_id)
        self._conversation_repository.save(conversation)
        return conversation

    def revoke_floor(self, conversation_id: str) -> Conversation:
        conversation = self.load_conversation(conversation_id)
        conversation.revoke_floor()
        self._conversation_repository.save(conversation)
        return conversation

    def invoke_with_floor(self, conversation_id: str) -> Conversation:
        """Ruft den Participant mit Rederecht auf und entzieht es danach."""
        conversation = self.load_conversation(conversation_id)

        if conversation.floor is None:
            raise NoFloorGranted(conversation_id)

        participant_id = conversation.floor

        if self._registry is None:
            raise AdapterNotFound(participant_id)
        adapter = self._registry.get_for(participant_id)

        participant = next(
            (p for p in conversation.participants if p.id == participant_id), None
        )
        if participant is None:
            raise ParticipantNotRegistered(participant_id, conversation_id)
        self._ensure_has_messages(conversation)

        snapshot = dataclasses.replace(conversation, messages=list(conversation.messages))
        snapshot = self._expand_workspace_refs(snapshot)
        provider = getattr(adapter, "provider", "")
        model = getattr(adapter, "_model", "")
        model = str(model) if isinstance(model, str) else ""
        started_at = datetime.now(timezone.utc)
        try:
            with request_logger(logger, operation="invoke_with_floor",
                                conversation_id=conversation_id, participant_id=participant_id):
                result = adapter.complete(snapshot, participant)
            response = completion_text(result)
            input_tokens, output_tokens = self._usage_tokens(result)
            self._audit("invoke_with_floor", conversation_id, participant_id,
                        provider=provider, model=model, success=True,
                        input_tokens=input_tokens, output_tokens=output_tokens)
            run_id = self._record_run("invoke", conversation_id, [participant_id], started_at,
                             "succeeded", provider=provider, model=model,
                             input_tokens=input_tokens, output_tokens=output_tokens)
        except Exception as exc:
            self._audit("invoke_with_floor", conversation_id, participant_id,
                        provider=provider, model=model, success=False,
                        error_message=type(exc).__name__)
            failed_run_id = self._record_run("invoke", conversation_id, [participant_id], started_at,
                             "failed", provider=provider, model=model,
                             error=type(exc).__name__)
            self._save_context_report(conversation_id, participant_id, exc, failed_run_id)
            raise

        message = self._store_model_response(conversation, participant_id, response)
        self._save_context_report(conversation_id, participant_id, result, run_id, message_id=message.id)

        conversation.revoke_floor()
        self._conversation_repository.save(conversation)
        return conversation

    def load_conversation(self, conversation_id: str):
        conversation = self._conversation_repository.load(conversation_id)

        if conversation is None:
            raise ConversationNotFound(conversation_id)

        conversation.messages = self._message_repository.list_by_conversation_id(
            conversation_id
        )
        conversation.participants = self._participant_repository.list_by_conversation_id(
            conversation_id
        )
        return conversation

    def list_conversations(self) -> list[Conversation]:
        return self._conversation_repository.list_all()

    def delete_conversation(self, conversation_id: str) -> None:
        conversation = self._conversation_repository.load(conversation_id)
        if conversation is None:
            raise ConversationNotFound(conversation_id)
        self._conversation_repository.delete(conversation_id)

    def list_tool_events_by_message(self, message_id: str) -> list[ToolEvent]:
        if self._tool_event_repo is None:
            return []
        return self._tool_event_repo.list_by_message(message_id)

    def list_tool_events_by_conversation(self, conversation_id: str) -> list[ToolEvent]:
        if self._tool_event_repo is None:
            return []
        return self._tool_event_repo.list_by_conversation(conversation_id)

    def add_user_message(self, conversation_id: str, content: str, origin: str | None = None) -> Conversation:
        conversation = self.load_conversation(conversation_id)
        message = conversation.add_user_message(content, origin=origin)
        self._message_repository.save(message)
        return conversation

    def register_participant(
        self,
        conversation_id: str,
        participant_id: str,
        participant_type: ParticipantType,
        name: str,
    ) -> Conversation:
        return self._participant_service.register_participant(
            conversation_id=conversation_id,
            participant_id=participant_id,
            participant_type=participant_type,
            name=name,
        )

    def delete_participant(self, conversation_id: str, participant_id: str) -> Conversation:
        return self._participant_service.delete_participant(conversation_id, participant_id)

    def add_model_message(
        self,
        conversation_id: str,
        participant_id: str,
        content: str,
        context_report_id: str | None = None,
        process_directives: bool = True,
    ):
        conversation = self.load_conversation(conversation_id)

        participant = next(
            (p for p in conversation.participants if p.id == participant_id),
            None,
        )
        if participant is None:
            raise ParticipantNotRegistered(
                participant_id=participant_id,
                conversation_id=conversation_id,
            )

        message = self._store_model_response(conversation, participant_id, content,
                                             process_directives=process_directives)
        if context_report_id and self._context_report_repo is not None:
            self._context_report_repo.link_message(context_report_id, message.id)
        return conversation

    def invoke_participant(
        self,
        conversation_id: str,
        participant_id: str,
        adapter: ModelAdapter | None = None,
    ) -> Conversation:
        conversation = self.load_conversation(conversation_id)

        participant = next(
            (p for p in conversation.participants if p.id == participant_id),
            None,
        )
        if participant is None:
            raise ParticipantNotRegistered(
                participant_id=participant_id,
                conversation_id=conversation_id,
            )

        if adapter is None:
            if self._registry is None:
                raise AdapterNotFound(participant_id)
            adapter = self._registry.get_for(participant_id)
        self._ensure_has_messages(conversation)

        snapshot = dataclasses.replace(conversation, messages=list(conversation.messages))
        snapshot = self._expand_workspace_refs(snapshot)
        provider = getattr(adapter, "provider", "")
        model = getattr(adapter, "_model", "")
        model = str(model) if isinstance(model, str) else ""
        started_at = datetime.now(timezone.utc)

        try:
            with request_logger(logger, operation="invoke_participant",
                                conversation_id=conversation_id, participant_id=participant_id):
                result = adapter.complete(snapshot, participant)
            response = completion_text(result)
            it, ot = self._usage_tokens(result)
            self._audit("invoke_participant", conversation_id, participant_id,
                        provider=provider, model=model, success=True,
                        input_tokens=it, output_tokens=ot)
            run_id = self._record_run("invoke", conversation_id, [participant_id], started_at,
                             "succeeded", provider=provider, model=model,
                             input_tokens=it, output_tokens=ot)
        except Exception as exc:
            self._audit("invoke_participant", conversation_id, participant_id,
                        provider=provider, model=model, success=False,
                        error_message=type(exc).__name__)
            failed_run_id = self._record_run("invoke", conversation_id, [participant_id], started_at,
                             "failed", provider=provider, model=model,
                             error=type(exc).__name__)
            self._save_context_report(conversation_id, participant_id, exc, failed_run_id)
            raise

        message = self._store_model_response(conversation, participant_id, response)
        self._save_context_report(conversation_id, participant_id, result, run_id, message_id=message.id)
        return conversation

    def stream_participant(
        self,
        conversation_id: str,
        participant_id: str,
        adapter: ModelAdapter | None = None,
    ) -> Iterator[str]:
        """Streamt Tokens vom Modell und speichert die vollständige Message am Ende.

        Adapter ohne stream()-Methode werden automatisch auf complete() zurückgefallen.
        """
        conversation = self.load_conversation(conversation_id)

        participant = next(
            (p for p in conversation.participants if p.id == participant_id),
            None,
        )
        if participant is None:
            raise ParticipantNotRegistered(
                participant_id=participant_id,
                conversation_id=conversation_id,
            )

        if adapter is None:
            if self._registry is None:
                raise AdapterNotFound(participant_id)
            adapter = self._registry.get_for(participant_id)
        self._ensure_has_messages(conversation)

        snapshot = dataclasses.replace(conversation, messages=list(conversation.messages))
        snapshot = self._expand_workspace_refs(snapshot)
        provider = getattr(adapter, "provider", "")
        model = getattr(adapter, "_model", "")
        model = str(model) if isinstance(model, str) else ""
        started_at = datetime.now(timezone.utc)
        logger.debug("stream_participant start",
                      extra={"conversation_id": conversation_id, "participant_id": participant_id})

        try:
            result = None
            if isinstance(adapter, StreamingModelAdapter):
                tokens: list[str] = []
                for token in adapter.stream(snapshot, participant):
                    if isinstance(token, Completion):
                        # Abschluss des Streams: Usage und Report, kein Text
                        result = token
                        continue
                    tokens.append(token)
                    yield token
                full_content = "".join(tokens)
            else:
                result = adapter.complete(snapshot, participant)
                full_content = completion_text(result)
                yield full_content

            input_tokens, output_tokens = self._usage_tokens(result)
            self._audit("stream_participant", conversation_id, participant_id,
                        provider=provider, model=model, success=True,
                        input_tokens=input_tokens, output_tokens=output_tokens)
            run_id = self._record_run("stream", conversation_id, [participant_id], started_at,
                             "succeeded", provider=provider, model=model,
                             input_tokens=input_tokens, output_tokens=output_tokens)
        except Exception as exc:
            self._audit("stream_participant", conversation_id, participant_id,
                        provider=provider, model=model, success=False,
                        error_message=type(exc).__name__)
            failed_run_id = self._record_run("stream", conversation_id, [participant_id], started_at,
                             "failed", provider=provider, model=model,
                             error=type(exc).__name__)
            self._save_context_report(conversation_id, participant_id, exc, failed_run_id)
            raise

        message = self._store_model_response(conversation, participant_id, full_content)
        self._save_context_report(conversation_id, participant_id, result, run_id, message_id=message.id)

    # ── Async-Methoden ───────────────────────────────────────────────────

    async def async_invoke_participant(
        self,
        conversation_id: str,
        participant_id: str,
        adapter=None,
    ) -> Conversation:
        """Async-Variante von invoke_participant — für async Adapter."""
        conversation = self.load_conversation(conversation_id)

        turn = await self.async_complete_turn(
            conversation_id=conversation_id,
            participant_id=participant_id,
            adapter=adapter,
            conversation=conversation,
        )

        message = self._store_model_response(conversation, participant_id, turn.text)
        if turn.context_report_id and self._context_report_repo is not None:
            self._context_report_repo.link_message(turn.context_report_id, message.id)
        return conversation

    async def async_complete_participant(
        self,
        conversation_id: str,
        participant_id: str,
        adapter=None,
        conversation: Conversation | None = None,
        snapshot: Conversation | None = None,
    ) -> str:
        """Wie async_complete_turn, liefert nur den Text."""
        turn = await self.async_complete_turn(
            conversation_id=conversation_id, participant_id=participant_id,
            adapter=adapter, conversation=conversation, snapshot=snapshot,
        )
        return turn.text

    async def async_complete_turn(
        self,
        conversation_id: str,
        participant_id: str,
        adapter=None,
        conversation: Conversation | None = None,
        snapshot: Conversation | None = None,
    ) -> "AgentTurn":
        """Erzeugt eine async Agent-Antwort ohne sie zu persistieren.

        Der Kontext-Report wird schon gespeichert (mit Run, ohne Nachricht);
        add_model_message(context_report_id=...) verknuepft ihn spaeter.

        ParallelOrchestrator nutzt diese Methode mit einem gemeinsamen Snapshot
        pro Gruppe, damit Participants innerhalb derselben Gruppe blind-parallel
        bleiben. Persistiert wird danach in stabiler Gruppenreihenfolge.
        """
        if conversation is None:
            conversation = self.load_conversation(conversation_id)

        participant = next(
            (p for p in conversation.participants if p.id == participant_id),
            None,
        )
        if participant is None:
            raise ParticipantNotRegistered(
                participant_id=participant_id,
                conversation_id=conversation_id,
            )

        if adapter is None:
            if self._registry is None:
                raise AdapterNotFound(participant_id)
            adapter = self._registry.get_for(participant_id)
        self._ensure_has_messages(conversation)

        if snapshot is None:
            snapshot = dataclasses.replace(conversation, messages=list(conversation.messages))
            snapshot = self._expand_workspace_refs(snapshot)
        provider = getattr(adapter, "provider", "")
        model = getattr(adapter, "_model", "")
        model = str(model) if isinstance(model, str) else ""
        started_at = datetime.now(timezone.utc)
        try:
            with request_logger(logger, operation="async_invoke_participant",
                                conversation_id=conversation_id, participant_id=participant_id):
                if inspect.iscoroutinefunction(adapter.complete):
                    result = await adapter.complete(snapshot, participant)
                else:
                    # Sync-Adapter (anthropic, openai, universal, resilient) wuerde die
                    # Event-Loop blockieren -> asyncio.gather waere de-facto sequenziell.
                    # asyncio.to_thread legt den sync-Call in einen Worker-Thread, sodass
                    # mehrere Adapter in derselben Gruppe wirklich gleichzeitig laufen.
                    result = await asyncio.to_thread(adapter.complete, snapshot, participant)
            response = completion_text(result)
            input_tokens, output_tokens = self._usage_tokens(result)
            self._audit("async_invoke_participant", conversation_id, participant_id,
                        provider=provider, model=model, success=True,
                        input_tokens=input_tokens, output_tokens=output_tokens)
            run_id = self._record_run("invoke", conversation_id, [participant_id], started_at,
                             "succeeded", provider=provider, model=model,
                             input_tokens=input_tokens, output_tokens=output_tokens)
        except Exception as exc:
            self._audit("async_invoke_participant", conversation_id, participant_id,
                        provider=provider, model=model, success=False,
                        error_message=type(exc).__name__)
            failed_run_id = self._record_run("invoke", conversation_id, [participant_id], started_at,
                             "failed", provider=provider, model=model,
                             error=type(exc).__name__)
            self._save_context_report(conversation_id, participant_id, exc, failed_run_id)
            raise

        report_id = self._save_context_report(conversation_id, participant_id, result, run_id)
        return AgentTurn(text=response, context_report_id=report_id)

    async def async_stream_participant(
        self,
        conversation_id: str,
        participant_id: str,
        adapter=None,
    ) -> AsyncIterator[str]:
        """Async-Variante von stream_participant — für async Streaming-Adapter."""
        conversation = self.load_conversation(conversation_id)

        participant = next(
            (p for p in conversation.participants if p.id == participant_id),
            None,
        )
        if participant is None:
            raise ParticipantNotRegistered(
                participant_id=participant_id,
                conversation_id=conversation_id,
            )

        if adapter is None:
            if self._registry is None:
                raise AdapterNotFound(participant_id)
            adapter = self._registry.get_for(participant_id)
        self._ensure_has_messages(conversation)

        snapshot = dataclasses.replace(conversation, messages=list(conversation.messages))
        snapshot = self._expand_workspace_refs(snapshot)
        provider = getattr(adapter, "provider", "")
        model = getattr(adapter, "_model", "")
        model = str(model) if isinstance(model, str) else ""
        started_at = datetime.now(timezone.utc)
        logger.debug("async_stream_participant start",
                      extra={"conversation_id": conversation_id, "participant_id": participant_id})

        tokens: list[str] = []
        result = None
        try:
            if hasattr(adapter, "stream"):
                async for token in adapter.stream(snapshot, participant):
                    if isinstance(token, Completion):
                        result = token
                        continue
                    tokens.append(token)
                    yield token
            else:
                if inspect.iscoroutinefunction(adapter.complete):
                    result = await adapter.complete(snapshot, participant)
                else:
                    result = adapter.complete(snapshot, participant)
                full = completion_text(result)
                tokens.append(full)
                yield full

            input_tokens, output_tokens = self._usage_tokens(result)
            self._audit("async_stream_participant", conversation_id, participant_id,
                        provider=provider, model=model, success=True,
                        input_tokens=input_tokens, output_tokens=output_tokens)
            run_id = self._record_run("stream", conversation_id, [participant_id], started_at,
                             "succeeded", provider=provider, model=model,
                             input_tokens=input_tokens, output_tokens=output_tokens)
        except Exception as exc:
            self._audit("async_stream_participant", conversation_id, participant_id,
                        provider=provider, model=model, success=False,
                        error_message=type(exc).__name__)
            failed_run_id = self._record_run("stream", conversation_id, [participant_id], started_at,
                             "failed", provider=provider, model=model,
                             error=type(exc).__name__)
            self._save_context_report(conversation_id, participant_id, exc, failed_run_id)
            raise

        full_content = "".join(tokens)
        message = self._store_model_response(conversation, participant_id, full_content)
        self._save_context_report(conversation_id, participant_id, result, run_id, message_id=message.id)
