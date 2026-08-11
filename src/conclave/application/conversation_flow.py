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
from conclave.application.ports import AuditRepository, ConversationRepository, MessageRepository, ModelAdapter, ParticipantRepository, RunRepository, StreamingModelAdapter
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
from conclave.domain.conversation import Conversation
from conclave.domain.errors import (
    AdapterNotFound,
    ConversationNotFound,
    EmptyConversation,
    NoFloorGranted,
    ParticipantNotRegistered,
)
from conclave.domain.participant import ParticipantType
from conclave.domain.run import Run, UsageRecord
from conclave.infrastructure.log import get_logger, request_logger

logger = get_logger("application.conversation_flow")


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

    def set_adapter_registry(self, registry: AdapterRegistry) -> None:
        self._registry = registry

    def set_audit_repository(self, audit_repo: AuditRepository) -> None:
        self._audit_repo = audit_repo

    def set_run_repository(self, run_repo: RunRepository) -> None:
        self._run_repo = run_repo

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
    ) -> None:
        if self._run_repo is None:
            return
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

    @staticmethod
    def _usage_tokens(adapter) -> tuple[int | None, int | None]:
        usage = getattr(adapter, "last_usage", None)
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
                original = match.group(0)
                resolved = resolve_workspace_path(filepath)
                if resolved is None:
                    content = content.replace(original, "[FEHLER: Pfad nicht erlaubt]")
                    continue
                if not is_agent_visible(resolved.path, root=resolved.root):
                    content = content.replace(original, f"[FEHLER: {filepath} nicht gefunden]")
                    continue
                if resolved.path.is_file():
                    if not assert_size_allowed(resolved.path, limit):
                        content = content.replace(original, f"[FEHLER: {filepath} ist zu gross]")
                        continue
                    try:
                        with open(resolved.path, "r", encoding="utf-8") as f:
                            file_content = f.read()
                        content = content.replace(
                            original,
                            f"\n--- Datei: {filepath} ---\n```\n{file_content}\n```\n"
                        )
                    except Exception:
                        content = content.replace(original, f"[FEHLER: {filepath} nicht lesbar]")
                else:
                    content = content.replace(original, f"[FEHLER: {filepath} nicht gefunden]")
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
        root = workspace_root()

        # @save(datei)...\n@endsave
        save_pattern = re.compile(
            r'@save\(([^)]+)\)\s*\n(.*?)(?:@endsave|$)',
            re.DOTALL,
        )
        def _save_replace(match):
            filepath = match.group(1).strip()
            file_content = match.group(2).strip()
            resolved = resolve_output_path(filepath, root=root)
            if resolved is None:
                return f"[FEHLER: Pfad '{filepath}' nicht erlaubt]"
            content_bytes = len(file_content.encode("utf-8"))
            if content_bytes > write_limit_bytes():
                return f"[FEHLER: Datei '{filepath}' ist zu gross]"
            try:
                os.makedirs(os.path.dirname(resolved.path), exist_ok=True)
                with open(resolved.path, "w", encoding="utf-8") as f:
                    f.write(file_content)
                return f"[Datei gespeichert: @workspace/output/{filepath}]"
            except Exception as e:
                return f"[FEHLER beim Speichern von '{filepath}': {e}]"
        content = save_pattern.sub(_save_replace, content)

        # @read(pfad)
        read_pattern = re.compile(r'@read\(([^)]+)\)')
        def _read_replace(match):
            filepath = match.group(1).strip()
            resolved = resolve_workspace_path(filepath, root=root)
            if resolved is None:
                return f"[FEHLER: Pfad '{filepath}' nicht erlaubt]"
            if not is_agent_visible(resolved.path, root=root) or not resolved.path.is_file():
                return f"[FEHLER: {filepath} nicht gefunden]"
            if not assert_size_allowed(resolved.path, agent_read_limit_bytes()):
                return f"[FEHLER: {filepath} ist zu gross]"
            try:
                with open(resolved.path, "r", encoding="utf-8") as f:
                    file_content = f.read()
                return f"\n--- Datei: {filepath} ---\n```\n{file_content}\n```\n"
            except Exception:
                return f"[FEHLER: {filepath} nicht lesbar]"
        content = read_pattern.sub(_read_replace, content)

        return content

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
                response = adapter.complete(snapshot, participant)
            input_tokens, output_tokens = self._usage_tokens(adapter)
            self._audit("invoke_with_floor", conversation_id, participant_id,
                        provider=provider, model=model, success=True,
                        input_tokens=input_tokens, output_tokens=output_tokens)
            self._record_run("invoke", conversation_id, [participant_id], started_at,
                             "succeeded", provider=provider, model=model,
                             input_tokens=input_tokens, output_tokens=output_tokens)
        except Exception as exc:
            self._audit("invoke_with_floor", conversation_id, participant_id,
                        provider=provider, model=model, success=False,
                        error_message=type(exc).__name__)
            self._record_run("invoke", conversation_id, [participant_id], started_at,
                             "failed", provider=provider, model=model,
                             error=type(exc).__name__)
            raise

        response = self._process_agent_directives(response)
        message = conversation.add_model_message(participant_id=participant_id, content=response)
        self._message_repository.save(message)

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

    def add_user_message(self, conversation_id: str, content: str) -> Conversation:
        conversation = self.load_conversation(conversation_id)
        message = conversation.add_user_message(content)
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

        message = conversation.add_model_message(
            participant_id=participant_id,
            content=content,
        )
        self._message_repository.save(message)
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
                response = adapter.complete(snapshot, participant)
            it, ot = self._usage_tokens(adapter)
            self._audit("invoke_participant", conversation_id, participant_id,
                        provider=provider, model=model, success=True,
                        input_tokens=it, output_tokens=ot)
            self._record_run("invoke", conversation_id, [participant_id], started_at,
                             "succeeded", provider=provider, model=model,
                             input_tokens=it, output_tokens=ot)
        except Exception as exc:
            self._audit("invoke_participant", conversation_id, participant_id,
                        provider=provider, model=model, success=False,
                        error_message=type(exc).__name__)
            self._record_run("invoke", conversation_id, [participant_id], started_at,
                             "failed", provider=provider, model=model,
                             error=type(exc).__name__)
            raise

        response = self._process_agent_directives(response)
        message = conversation.add_model_message(
            participant_id=participant_id,
            content=response,
        )
        self._message_repository.save(message)
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
            if isinstance(adapter, StreamingModelAdapter):
                tokens: list[str] = []
                for token in adapter.stream(snapshot, participant):
                    tokens.append(token)
                    yield token
                full_content = "".join(tokens)
            else:
                full_content = adapter.complete(snapshot, participant)
                yield full_content

            input_tokens, output_tokens = self._usage_tokens(adapter)
            self._audit("stream_participant", conversation_id, participant_id,
                        provider=provider, model=model, success=True,
                        input_tokens=input_tokens, output_tokens=output_tokens)
            self._record_run("stream", conversation_id, [participant_id], started_at,
                             "succeeded", provider=provider, model=model,
                             input_tokens=input_tokens, output_tokens=output_tokens)
        except Exception as exc:
            self._audit("stream_participant", conversation_id, participant_id,
                        provider=provider, model=model, success=False,
                        error_message=type(exc).__name__)
            self._record_run("stream", conversation_id, [participant_id], started_at,
                             "failed", provider=provider, model=model,
                             error=type(exc).__name__)
            raise

        message = conversation.add_model_message(
            participant_id=participant_id,
            content=full_content,
        )
        self._message_repository.save(message)

    # ── Async-Methoden ───────────────────────────────────────────────────

    async def async_invoke_participant(
        self,
        conversation_id: str,
        participant_id: str,
        adapter=None,
    ) -> Conversation:
        """Async-Variante von invoke_participant — für async Adapter."""
        conversation = self.load_conversation(conversation_id)

        response = await self.async_complete_participant(
            conversation_id=conversation_id,
            participant_id=participant_id,
            adapter=adapter,
            conversation=conversation,
        )

        message = conversation.add_model_message(
            participant_id=participant_id,
            content=response,
        )
        self._message_repository.save(message)
        return conversation

    async def async_complete_participant(
        self,
        conversation_id: str,
        participant_id: str,
        adapter=None,
        conversation: Conversation | None = None,
        snapshot: Conversation | None = None,
    ) -> str:
        """Erzeugt eine async Agent-Antwort ohne sie zu persistieren.

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
                    response = await adapter.complete(snapshot, participant)
                else:
                    # Sync-Adapter (anthropic, openai, universal, resilient) wuerde die
                    # Event-Loop blockieren -> asyncio.gather waere de-facto sequenziell.
                    # asyncio.to_thread legt den sync-Call in einen Worker-Thread, sodass
                    # mehrere Adapter in derselben Gruppe wirklich gleichzeitig laufen.
                    response = await asyncio.to_thread(adapter.complete, snapshot, participant)
            input_tokens, output_tokens = self._usage_tokens(adapter)
            self._audit("async_invoke_participant", conversation_id, participant_id,
                        provider=provider, model=model, success=True,
                        input_tokens=input_tokens, output_tokens=output_tokens)
            self._record_run("invoke", conversation_id, [participant_id], started_at,
                             "succeeded", provider=provider, model=model,
                             input_tokens=input_tokens, output_tokens=output_tokens)
        except Exception as exc:
            self._audit("async_invoke_participant", conversation_id, participant_id,
                        provider=provider, model=model, success=False,
                        error_message=type(exc).__name__)
            self._record_run("invoke", conversation_id, [participant_id], started_at,
                             "failed", provider=provider, model=model,
                             error=type(exc).__name__)
            raise

        return self._process_agent_directives(response)

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
        try:
            if hasattr(adapter, "stream"):
                async for token in adapter.stream(snapshot, participant):
                    tokens.append(token)
                    yield token
            else:
                if inspect.iscoroutinefunction(adapter.complete):
                    full = await adapter.complete(snapshot, participant)
                else:
                    full = adapter.complete(snapshot, participant)
                tokens.append(full)
                yield full

            input_tokens, output_tokens = self._usage_tokens(adapter)
            self._audit("async_stream_participant", conversation_id, participant_id,
                        provider=provider, model=model, success=True,
                        input_tokens=input_tokens, output_tokens=output_tokens)
            self._record_run("stream", conversation_id, [participant_id], started_at,
                             "succeeded", provider=provider, model=model,
                             input_tokens=input_tokens, output_tokens=output_tokens)
        except Exception as exc:
            self._audit("async_stream_participant", conversation_id, participant_id,
                        provider=provider, model=model, success=False,
                        error_message=type(exc).__name__)
            self._record_run("stream", conversation_id, [participant_id], started_at,
                             "failed", provider=provider, model=model,
                             error=type(exc).__name__)
            raise

        full_content = "".join(tokens)
        message = conversation.add_model_message(
            participant_id=participant_id,
            content=full_content,
        )
        self._message_repository.save(message)
