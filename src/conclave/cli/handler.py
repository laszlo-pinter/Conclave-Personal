# src/conclave/cli/handler.py

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import os
from datetime import datetime, timezone

from conclave.application.agent_service import AgentService
from conclave.application.conversation_flow import ConversationFlowService
from conclave.application.orchestrator import Orchestrator, ParallelOrchestrator
from conclave.application.workspace_security import (
    assert_size_allowed,
    is_hidden_workspace_path,
    resolve_workspace_path,
    text_size,
    ui_read_limit_bytes,
    workspace_root,
    write_limit_bytes,
)
from conclave.domain.agent import Agent
from conclave.domain.errors import (
    AdapterNotFound,
    AgentAlreadyExists,
    AgentNotFound,
    ConversationNotFound,
    EmptyConversation,
    ParticipantAlreadyRegistered,
)
from conclave.domain.participant import ParticipantType


MAX_ORCHESTRATION_PARTICIPANTS = 20
MAX_AUTO_LOOP_ROUNDS = 50
MAX_STOP_SIGNAL_LENGTH = 128
AUTO_LOOP_ROTATIONS = {"none", "round_robin"}


def normalize_participant_sequence(sequence: list[str], *, field: str = "sequence") -> list[str]:
    if not isinstance(sequence, list):
        raise ValueError(f"{field} muss eine Liste von Participant-IDs sein.")
    normalized: list[str] = []
    for item in sequence:
        if not isinstance(item, str):
            raise ValueError(f"{field} darf nur Participant-IDs als Strings enthalten.")
        participant_id = item.strip()
        if not participant_id:
            raise ValueError(f"{field} darf keine leeren Participant-IDs enthalten.")
        normalized.append(participant_id)
    if not normalized:
        raise ValueError(f"{field} muss mindestens eine Participant-ID enthalten.")
    if len(normalized) > MAX_ORCHESTRATION_PARTICIPANTS:
        raise ValueError(
            f"{field} darf maximal {MAX_ORCHESTRATION_PARTICIPANTS} Participant-IDs enthalten."
        )
    return normalized


def normalize_parallel_groups(groups: list[list[str]]) -> list[list[str]]:
    if not isinstance(groups, list):
        raise ValueError("groups muss eine Liste von Participant-Gruppen sein.")
    normalized: list[list[str]] = []
    total = 0
    for index, group in enumerate(groups, start=1):
        normalized_group = normalize_participant_sequence(group, field=f"groups[{index}]")
        total += len(normalized_group)
        normalized.append(normalized_group)
    if not normalized:
        raise ValueError("groups muss mindestens eine Participant-Gruppe enthalten.")
    if total > MAX_ORCHESTRATION_PARTICIPANTS:
        raise ValueError(
            f"groups darf insgesamt maximal {MAX_ORCHESTRATION_PARTICIPANTS} Participant-IDs enthalten."
        )
    return normalized


def normalize_auto_loop_options(
    sequence: list[str],
    stop_signal: str = "@done",
    max_rounds: int = 20,
    rotation: str = "none",
) -> tuple[list[str], str, int, str]:
    normalized_sequence = normalize_participant_sequence(sequence)
    if not isinstance(stop_signal, str):
        raise ValueError("stop_signal muss ein String sein.")
    normalized_signal = stop_signal.strip()
    if not normalized_signal:
        raise ValueError("stop_signal darf nicht leer sein.")
    if len(normalized_signal) > MAX_STOP_SIGNAL_LENGTH:
        raise ValueError(
            f"stop_signal darf maximal {MAX_STOP_SIGNAL_LENGTH} Zeichen lang sein."
        )
    try:
        normalized_rounds = int(max_rounds)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_rounds muss eine ganze Zahl sein.") from exc
    if normalized_rounds < 1 or normalized_rounds > MAX_AUTO_LOOP_ROUNDS:
        raise ValueError(f"max_rounds muss zwischen 1 und {MAX_AUTO_LOOP_ROUNDS} liegen.")
    if not isinstance(rotation, str):
        raise ValueError("rotation muss ein String sein.")
    normalized_rotation = rotation.strip().lower().replace("-", "_") or "none"
    if normalized_rotation not in AUTO_LOOP_ROTATIONS:
        allowed = ", ".join(sorted(AUTO_LOOP_ROTATIONS))
        raise ValueError(f"rotation muss einer dieser Werte sein: {allowed}.")
    return normalized_sequence, normalized_signal, normalized_rounds, normalized_rotation


def auto_loop_round_sequence(sequence: list[str], round_number: int, rotation: str) -> list[str]:
    if rotation != "round_robin" or len(sequence) < 2:
        return list(sequence)
    offset = (round_number - 1) % len(sequence)
    return sequence[offset:] + sequence[:offset]


@dataclass
class CLIResult:
    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)


class CLIHandler:
    def __init__(self, service: ConversationFlowService, agent_service: AgentService | None = None,
                 provider_fallback_keys: dict[str, str] | None = None):
        self._service = service
        self._agent_service = agent_service
        # Provider-Map fuer ENV/Config-Fallback-Keys (z.B. anthropic -> ANTHROPIC_API_KEY).
        # Wird nur fuer die UI-Anzeige (api_key_set) genutzt, nicht fuer den Adapter-Build.
        self._provider_fallback_keys = provider_fallback_keys or {}

    def _agent_to_dict(self, a: Agent) -> dict:
        # api_key_set spiegelt den effektiven Stand: entweder eigener Key in DB
        # ODER ein Provider-Fallback-Key (aus .env / ConclaveConfig) verfuegbar.
        effective_key = bool(a.api_key) or bool(self._fallback_key_for_agent(a))
        return {
            "id": a.id, "name": a.name, "provider": a.provider,
            "model": a.model, "role": a.role, "topic": a.topic,
            "system_prompt": a.system_prompt,
            "api_key_set": effective_key,
            "preset": a.preset,
            "api_url": a.api_url,
            "response_path": a.response_path,
            "message_format": a.message_format,
            "created_at": a.created_at.isoformat(),
        }

    def _fallback_key_for_agent(self, agent: Agent) -> str:
        if self._provider_fallback_keys.get(agent.provider):
            return self._provider_fallback_keys[agent.provider]
        preset_name = agent.preset or agent.provider
        try:
            from conclave.infrastructure.universal.presets import get_preset
        except ImportError:
            return ""
        preset = get_preset(preset_name) or {}
        key_env = preset.get("api_key_env", "")
        return os.environ.get(key_env, "") if key_env else ""

    def _run_to_dict(self, run) -> dict:
        usage = None
        if run.usage is not None:
            usage = {
                "provider": run.usage.provider,
                "model": run.usage.model,
                "input_tokens": run.usage.input_tokens,
                "output_tokens": run.usage.output_tokens,
                "total_tokens": run.usage.total_tokens,
            }
        return {
            "id": run.id,
            "conversation_id": run.conversation_id,
            "kind": run.kind,
            "participants": run.participants,
            "started_at": run.started_at.isoformat(),
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "status": run.status,
            "error": run.error,
            "usage": usage,
        }

    def test_agent(self, agent_id: str) -> dict:
        """Testet ob ein Agent erreichbar ist."""
        if not self._agent_service:
            return {"success": False, "message": "AgentService nicht verfuegbar."}
        try:
            agent = self._agent_service.get_agent(agent_id)
        except AgentNotFound:
            return {"success": False, "message": f"Agent '{agent_id}' nicht gefunden."}
        return self._test_agent_connection(agent)

    def _test_agent_connection(self, agent) -> dict:
        """Sendet eine Mini-Anfrage an den Provider."""
        started = datetime.now(timezone.utc)
        try:
            from conclave.cli.bootstrap import _make_adapter
            adapter = _make_adapter(agent, api_key=agent.api_key or self._fallback_key_for_agent(agent))
            if adapter is None:
                return {
                    "success": False,
                    "status": "not_configured",
                    "provider": agent.provider,
                    "model": agent.model,
                    "message": "Kein Adapter konfiguriert.",
                    "hint": "API-Key, Preset oder API-URL pruefen.",
                }
            from conclave.domain.conversation import Conversation
            from conclave.domain.participant import Participant, ParticipantType
            conv = Conversation(id="test", topic="test")
            from conclave.domain.message import Message, MessageAuthorType
            conv.messages = [Message(
                id="t1", conversation_id="test", author_type=MessageAuthorType.USER,
                author_id=None, content="Sag nur: OK", sequence=1,
                created_at=datetime.now(timezone.utc),
            )]
            part = Participant(id=agent.id, conversation_id="test",
                               participant_type=ParticipantType.MODEL, name=agent.name)
            response = adapter.complete(conv, part)
            latency_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
            return {
                "success": True,
                "status": "ok",
                "provider": agent.provider,
                "model": agent.model,
                "latency_ms": latency_ms,
                "message": f"Antwort: {response[:100]}",
            }
        except Exception as e:
            latency_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
            return {
                "success": False,
                "status": "error",
                "provider": agent.provider,
                "model": agent.model,
                "latency_ms": latency_ms,
                "message": str(e)[:200],
                "hint": "Provider erreichbar, API-Key und Modellnamen pruefen.",
            }

    def list_agents(self) -> CLIResult:
        if not self._agent_service:
            return CLIResult(success=False, message="AgentService nicht verfügbar.")
        agents = self._agent_service.list_agents()
        return CLIResult(success=True, message=f"{len(agents)} Agent(en).",
                         data={"agents": [self._agent_to_dict(a) for a in agents]})

    def get_agent(self, agent_id: str) -> CLIResult:
        if not self._agent_service:
            return CLIResult(success=False, message="AgentService nicht verfügbar.")
        try:
            a = self._agent_service.get_agent(agent_id)
            return CLIResult(success=True, message="ok", data=self._agent_to_dict(a))
        except AgentNotFound:
            return CLIResult(success=False, message=f"Agent '{agent_id}' nicht gefunden.")

    def create_agent(self, agent: Agent) -> CLIResult:
        if not self._agent_service:
            return CLIResult(success=False, message="AgentService nicht verfügbar.")
        try:
            self._agent_service.create_agent(agent)
            return CLIResult(success=True, message=f"Agent '{agent.id}' erstellt.",
                             data={"id": agent.id})
        except AgentAlreadyExists:
            return CLIResult(success=False, message=f"Agent '{agent.id}' existiert bereits.")

    def update_agent(self, agent: Agent) -> CLIResult:
        if not self._agent_service:
            return CLIResult(success=False, message="AgentService nicht verfügbar.")
        try:
            self._agent_service.update_agent(agent)
            return CLIResult(success=True, message=f"Agent '{agent.id}' aktualisiert.",
                             data={"id": agent.id})
        except AgentNotFound:
            return CLIResult(success=False, message=f"Agent '{agent.id}' nicht gefunden.")

    def delete_agent(self, agent_id: str) -> CLIResult:
        if not self._agent_service:
            return CLIResult(success=False, message="AgentService nicht verfügbar.")
        try:
            self._agent_service.delete_agent(agent_id)
            return CLIResult(success=True, message=f"Agent '{agent_id}' gelöscht.",
                             data={"id": agent_id})
        except AgentNotFound:
            return CLIResult(success=False, message=f"Agent '{agent_id}' nicht gefunden.")

    def set_agent_key(self, agent_id: str, api_key: str) -> CLIResult:
        if not self._agent_service:
            return CLIResult(success=False, message="AgentService nicht verfügbar.")
        try:
            agent = self._agent_service.get_agent(agent_id)
            updated = Agent(
                id=agent.id, name=agent.name, provider=agent.provider,
                model=agent.model, api_key=api_key,
                role=agent.role, topic=agent.topic,
                system_prompt=agent.system_prompt, created_at=agent.created_at,
            )
            self._agent_service.update_agent(updated)
            return CLIResult(success=True, message=f"API-Key für Agent '{agent_id}' gesetzt.",
                             data={"id": agent_id})
        except AgentNotFound:
            return CLIResult(success=False, message=f"Agent '{agent_id}' nicht gefunden.")

    def list_conversations(self) -> CLIResult:
        conversations = self._service.list_conversations()
        return CLIResult(
            success=True,
            message=f"{len(conversations)} Conversation(s) gefunden.",
            data={
                "conversations": [
                    {
                        "id": c.id,
                        "status": c.status,
                        "topic": c.topic,
                        "created_at": c.created_at.isoformat(),
                    }
                    for c in conversations
                ]
            },
        )

    def set_topic(self, conversation_id: str, topic: str) -> CLIResult:
        try:
            self._service.set_topic(conversation_id, topic)
        except ConversationNotFound:
            return CLIResult(success=False, message=f"Conversation '{conversation_id}' nicht gefunden.")
        return CLIResult(success=True, message=f"Thema gesetzt: {topic}", data={"topic": topic})

    def set_rules(self, conversation_id: str, rules: str) -> CLIResult:
        try:
            self._service.set_rules(conversation_id, rules)
        except ConversationNotFound:
            return CLIResult(success=False, message=f"Conversation '{conversation_id}' nicht gefunden.")
        return CLIResult(success=True, message="Regeln gesetzt.", data={"rules": rules})

    def grant_floor(self, conversation_id: str, participant_id: str) -> CLIResult:
        from conclave.domain.errors import ParticipantNotRegistered
        try:
            self._service.grant_floor(conversation_id, participant_id)
        except ConversationNotFound:
            return CLIResult(success=False, message=f"Conversation '{conversation_id}' nicht gefunden.")
        except ParticipantNotRegistered:
            return CLIResult(success=False, message=f"Participant '{participant_id}' nicht registriert.")
        return CLIResult(success=True, message=f"'{participant_id}' hat das Wort.", data={"floor": participant_id})

    def revoke_floor(self, conversation_id: str) -> CLIResult:
        try:
            self._service.revoke_floor(conversation_id)
        except ConversationNotFound:
            return CLIResult(success=False, message=f"Conversation '{conversation_id}' nicht gefunden.")
        return CLIResult(success=True, message="Rederecht entzogen.", data={})

    def invoke_with_floor(self, conversation_id: str) -> CLIResult:
        from conclave.domain.errors import AdapterNotFound, NoFloorGranted
        try:
            updated = self._service.invoke_with_floor(conversation_id)
        except ConversationNotFound:
            return CLIResult(success=False, message=f"Conversation '{conversation_id}' nicht gefunden.")
        except NoFloorGranted:
            return CLIResult(success=False, message="Kein Participant hat aktuell das Rederecht.")
        except EmptyConversation as e:
            return CLIResult(
                success=False,
                message=str(e),
                data={"type": "EmptyConversation", "status": 400},
            )
        except AdapterNotFound as e:
            return CLIResult(success=False, message=f"Kein Adapter für '{e.participant_id}' registriert.")
        message = updated.messages[-1]
        return CLIResult(
            success=True, message="Antwort erhalten.",
            data={"participant_id": message.author_id, "content": message.content, "sequence": message.sequence},
        )

    def delete_conversation(self, conversation_id: str) -> CLIResult:
        try:
            self._service.delete_conversation(conversation_id)
        except ConversationNotFound:
            return CLIResult(
                success=False,
                message=f"Conversation '{conversation_id}' nicht gefunden.",
            )
        return CLIResult(
            success=True,
            message=f"Conversation '{conversation_id}' gelöscht.",
            data={"conversation_id": conversation_id},
        )

    def new_conversation(self) -> CLIResult:
        conversation = self._service.create_conversation()
        return CLIResult(
            success=True,
            message=f"Conversation erstellt: {conversation.id}",
            data={"conversation_id": conversation.id},
        )

    def show_conversation(self, conversation_id: str) -> CLIResult:
        try:
            conversation = self._service.load_conversation(conversation_id)
        except ConversationNotFound:
            return CLIResult(
                success=False,
                message=f"Conversation '{conversation_id}' nicht gefunden.",
            )

        return CLIResult(
            success=True,
            message=f"Conversation {conversation_id}",
            data={
                "id": conversation.id,
                "status": conversation.status,
                "message_count": len(conversation.messages),
                "participant_count": len(conversation.participants),
                "messages": [
                    {
                        "sequence": m.sequence,
                        "author_type": m.author_type.value,
                        "author_id": m.author_id,
                        "content": m.content,
                    }
                    for m in conversation.messages
                ],
                "participants": [
                    {
                        "id": p.id,
                        "name": p.name,
                        "type": p.participant_type.value,
                    }
                    for p in conversation.participants
                ],
                "rules": conversation.rules,
            },
        )

    def add_participant(
        self,
        conversation_id: str,
        participant_id: str,
        name: str,
        participant_type: ParticipantType,
    ) -> CLIResult:
        try:
            self._service.register_participant(
                conversation_id=conversation_id,
                participant_id=participant_id,
                participant_type=participant_type,
                name=name,
            )
        except ConversationNotFound:
            return CLIResult(
                success=False,
                message=f"Conversation '{conversation_id}' nicht gefunden.",
            )
        except ParticipantAlreadyRegistered:
            return CLIResult(
                success=False,
                message=f"Participant '{participant_id}' ist bereits registriert.",
            )

        return CLIResult(
            success=True,
            message=f"Participant '{name}' ({participant_id}) registriert.",
            data={"participant_id": participant_id},
        )

    def delete_participant(self, conversation_id: str, participant_id: str) -> CLIResult:
        try:
            self._service.delete_participant(conversation_id, participant_id)
        except ConversationNotFound:
            return CLIResult(success=False, message=f"Conversation '{conversation_id}' nicht gefunden.")
        except Exception as e:
            if type(e).__name__ == "ParticipantNotRegistered":
                return CLIResult(success=False, message=f"Participant '{participant_id}' nicht registriert.")
            raise
        return CLIResult(success=True, message=f"Participant '{participant_id}' geloescht.",
                         data={"participant_id": participant_id})

    def add_message(self, conversation_id: str, content: str) -> CLIResult:
        try:
            updated = self._service.add_user_message(conversation_id, content)
        except ConversationNotFound:
            return CLIResult(
                success=False,
                message=f"Conversation '{conversation_id}' nicht gefunden.",
            )

        message = updated.messages[-1]
        return CLIResult(
            success=True,
            message=f"Message [{message.sequence}] hinzugefügt.",
            data={"sequence": message.sequence, "content": content},
        )

    def invoke_participant(
        self, conversation_id: str, participant_id: str
    ) -> CLIResult:
        try:
            updated = self._service.invoke_participant(
                conversation_id=conversation_id,
                participant_id=participant_id,
            )
        except ConversationNotFound:
            return CLIResult(
                success=False,
                message=f"Conversation '{conversation_id}' nicht gefunden.",
            )
        except AdapterNotFound:
            return CLIResult(
                success=False,
                message=f"Kein Adapter für Participant '{participant_id}' registriert.",
            )
        except EmptyConversation as e:
            return CLIResult(
                success=False,
                message=str(e),
                data={"type": "EmptyConversation", "status": 400},
            )

        message = updated.messages[-1]
        return CLIResult(
            success=True,
            message=f"Antwort von '{participant_id}' erhalten.",
            data={
                "participant_id": participant_id,
                "content": message.content,
                "sequence": message.sequence,
            },
        )

    def orchestrate(
        self, conversation_id: str, sequence: list[str]
    ) -> CLIResult:
        try:
            sequence = normalize_participant_sequence(sequence)
        except ValueError as exc:
            return CLIResult(
                success=False,
                message=str(exc),
                data={"type": "ValidationError", "status": 400},
            )
        orchestrator = Orchestrator(self._service)
        result = orchestrator.run(conversation_id=conversation_id, sequence=sequence)

        if not result.success:
            return CLIResult(
                success=False,
                message=result.error,
                data={"type": result.error_type, "status": result.status},
            )

        return CLIResult(
            success=True,
            message=f"{len(result.responses)} Antwort(en) erhalten.",
            data={
                "responses": [
                    {
                        "participant_id": r.participant_id,
                        "content": r.content,
                        "sequence": r.sequence,
                    }
                    for r in result.responses
                ]
            },
        )

    def orchestrate_parallel(
        self, conversation_id: str, groups: list[list[str]]
    ) -> CLIResult:
        import asyncio
        try:
            groups = normalize_parallel_groups(groups)
        except ValueError as exc:
            return CLIResult(
                success=False,
                message=str(exc),
                data={"type": "ValidationError", "status": 400},
            )
        orchestrator = ParallelOrchestrator(self._service)
        result = asyncio.run(
            orchestrator.run(conversation_id=conversation_id, groups=groups)
        )

        if not result.success:
            return CLIResult(
                success=False,
                message=result.error,
                data={"type": result.error_type, "status": result.status},
            )

        return CLIResult(
            success=True,
            message=f"{len(result.responses)} Antwort(en) erhalten.",
            data={
                "responses": [
                    {
                        "participant_id": r.participant_id,
                        "content": r.content,
                        "sequence": r.sequence,
                    }
                    for r in result.responses
                ]
            },
        )

    def auto_loop(
        self,
        conversation_id: str,
        sequence: list[str],
        stop_signal: str = "@done",
        max_rounds: int = 20,
        rotation: str = "none",
    ):
        """Generator: fuehrt bis zu max_rounds Runden durch.

        Jede Runde ruft alle Participants in sequence der Reihe nach auf.
        Nach jeder Antwort wird geprueft ob stop_signal (case-insensitiv) enthalten ist.
        """
        sequence, stop_signal, max_rounds, rotation = normalize_auto_loop_options(
            sequence=sequence,
            stop_signal=stop_signal,
            max_rounds=max_rounds,
            rotation=rotation,
        )
        yield {
            "event": "start",
            "max_rounds": max_rounds,
            "sequence": sequence,
            "stop_signal": stop_signal,
            "rotation": rotation,
        }

        for round_n in range(1, max_rounds + 1):
            round_sequence = auto_loop_round_sequence(sequence, round_n, rotation)
            for pid in round_sequence:
                yield {
                    "event": "invoke",
                    "round": round_n,
                    "participant": pid,
                    "round_sequence": round_sequence,
                }

                result = self.invoke_participant(conversation_id, pid)

                if not result.success:
                    yield {
                        "event": "stop",
                        "reason": "error",
                        "participant": pid,
                        "round": round_n,
                        "message": result.message,
                    }
                    return

                content = result.data.get("content", "")
                yield {
                    "event": "response",
                    "round": round_n,
                    "participant": pid,
                    "content": content,
                    "round_sequence": round_sequence,
                }

                if stop_signal.lower() in content.lower():
                    yield {
                        "event": "stop",
                        "reason": "signal",
                        "signal": stop_signal,
                        "participant": pid,
                        "round": round_n,
                    }
                    return

        yield {"event": "stop", "reason": "max_rounds", "rounds": max_rounds}

    def stream_participant(
        self, conversation_id: str, participant_id: str
    ):
        """Gibt einen Iterator über Tokens zurück."""
        return self._service.stream_participant(conversation_id, participant_id)

    # ── Personal Export ─────────────────────────────────────────────────

    def export_conversation(self, conversation_id: str) -> CLIResult:
        from conclave.application.data_export_service import DataExportService
        export_svc = DataExportService(self._service)
        data = export_svc.export_conversation(conversation_id)
        return CLIResult(success=True, message="Export erstellt.", data=data)

    def token_usage(self) -> CLIResult:
        if not self._service._audit_repo:
            return CLIResult(success=False, message="AuditRepository nicht verfuegbar.")
        summary = self._service._audit_repo.get_usage_summary()
        return CLIResult(success=True, message="ok", data={"usage": summary})

    def conversation_usage(self) -> CLIResult:
        if not self._service._audit_repo:
            return CLIResult(success=False, message="AuditRepository nicht verfuegbar.")
        rows = self._service._audit_repo.get_usage_by_conversation()
        convs = {}
        for r in rows:
            cid = r["conversation_id"]
            if cid not in convs:
                convs[cid] = {
                    "conversation_id": cid,
                    "topic": r["topic"],
                    "status": r["status"],
                    "providers": [],
                    "totals": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "calls": 0},
                }
            convs[cid]["providers"].append({
                "provider": r["provider"], "model": r["model"],
                "calls": r["calls"], "input_tokens": r["input_tokens"],
                "output_tokens": r["output_tokens"], "total_tokens": r["total_tokens"],
            })
            convs[cid]["totals"]["input_tokens"] += r["input_tokens"]
            convs[cid]["totals"]["output_tokens"] += r["output_tokens"]
            convs[cid]["totals"]["total_tokens"] += r["total_tokens"]
            convs[cid]["totals"]["calls"] += r["calls"]
        result = sorted(convs.values(), key=lambda c: c["totals"]["total_tokens"], reverse=True)
        grand = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "calls": 0}
        for c in result:
            for k in grand:
                grand[k] += c["totals"][k]
        return CLIResult(success=True, message="ok",
                         data={"conversations": result, "grand_totals": grand})

    def list_runs(self, conversation_id: str | None = None, limit: int = 100) -> CLIResult:
        if not self._service._run_repo:
            return CLIResult(success=False, message="RunRepository nicht verfuegbar.")
        if conversation_id:
            runs = self._service._run_repo.list_by_conversation(conversation_id, limit=limit)
        else:
            runs = self._service._run_repo.list_all(limit=limit)
        return CLIResult(success=True, message="ok",
                         data={"runs": [self._run_to_dict(r) for r in runs]})

    def get_run(self, run_id: str) -> CLIResult:
        if not self._service._run_repo:
            return CLIResult(success=False, message="RunRepository nicht verfuegbar.")
        run = self._service._run_repo.get(run_id)
        if run is None:
            return CLIResult(success=False, message=f"Run '{run_id}' nicht gefunden.")
        return CLIResult(success=True, message="ok", data=self._run_to_dict(run))

    # ── Workspace + Backup ──────────────────────────────────────────────

    def _workspace_root(self) -> Path:
        return workspace_root()

    def _safe_workspace_path(self, relative_path: str) -> Path | None:
        root = self._workspace_root()
        resolved = resolve_workspace_path(relative_path, root=root)
        return resolved.path if resolved else None

    def workspace_list(self) -> CLIResult:
        root = self._workspace_root()
        if not root.is_dir():
            return CLIResult(success=True, message="Workspace leer.", data={"files": []})
        files = []
        for path in root.rglob("*"):
            if path.is_file() and not is_hidden_workspace_path(path, root=root):
                files.append({
                    "path": path.relative_to(root).as_posix(),
                    "size": path.stat().st_size,
                    "modified": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                })
        files.sort(key=lambda item: item["path"])
        return CLIResult(success=True, message=f"{len(files)} Datei(en).", data={"files": files})

    def workspace_read(self, relative_path: str) -> CLIResult:
        path = self._safe_workspace_path(relative_path)
        if path is None:
            return CLIResult(success=False, message="Pfad nicht erlaubt.")
        if is_hidden_workspace_path(path, root=self._workspace_root()):
            return CLIResult(success=False, message="Pfad nicht erlaubt.")
        if not path.is_file():
            return CLIResult(success=False, message="Datei nicht gefunden.")
        if not assert_size_allowed(path, ui_read_limit_bytes()):
            return CLIResult(success=False, message=f"Datei zu gross (Limit: {ui_read_limit_bytes()} Bytes).")
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return CLIResult(success=False, message="Binaerdatei nicht lesbar.")
        return CLIResult(success=True, message="ok",
                         data={"path": path.relative_to(self._workspace_root()).as_posix(),
                               "content": content})

    def workspace_write(self, relative_path: str, content: str) -> CLIResult:
        path = self._safe_workspace_path(relative_path)
        if path is None:
            return CLIResult(success=False, message="Pfad nicht erlaubt.")
        if is_hidden_workspace_path(path, root=self._workspace_root()):
            return CLIResult(success=False, message="Pfad nicht erlaubt.")
        if text_size(content) > write_limit_bytes():
            return CLIResult(success=False, message=f"Datei zu gross (Limit: {write_limit_bytes()} Bytes).")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return CLIResult(success=True, message="Datei gespeichert.",
                         data={"path": path.relative_to(self._workspace_root()).as_posix(),
                               "size": len(content)})

    def create_backup(self, db_path: Path | None = None, backup_dir: Path | None = None) -> CLIResult:
        root = self._workspace_root()
        if backup_dir is None:
            backup_dir_env = os.environ.get("CONCLAVE_BACKUP_DIR", "").strip()
            backup_dir = Path(backup_dir_env) if backup_dir_env else root.parent / "backups"
        from conclave.runtime.backup import create_backup_archive
        backup_path = create_backup_archive(db_path=db_path, workspace_root=root, backup_dir=backup_dir)
        return CLIResult(success=True, message="Backup erstellt.",
                         data={"backup_path": str(backup_path), "format": "zip"})

    def restore_backup(
        self,
        backup_path: Path,
        db_path: Path | None = None,
        backup_dir: Path | None = None,
        replace_workspace: bool = True,
    ) -> CLIResult:
        root = self._workspace_root()
        if backup_dir is None:
            backup_dir_env = os.environ.get("CONCLAVE_BACKUP_DIR", "").strip()
            backup_dir = Path(backup_dir_env) if backup_dir_env else root.parent / "backups"
        from conclave.runtime.backup import restore_backup_archive
        try:
            result = restore_backup_archive(
                backup_path=backup_path,
                db_path=db_path,
                workspace_root=root,
                backup_dir=backup_dir,
                replace_workspace=replace_workspace,
            )
        except ValueError as exc:
            return CLIResult(success=False, message=str(exc), data={"status": "invalid_backup"})
        except OSError:
            return CLIResult(success=False, message="Restore fehlgeschlagen.", data={"status": "restore_failed"})
        return CLIResult(
            success=True,
            message="Backup wiederhergestellt.",
            data={
                "status": "restored",
                "backup_path": str(backup_path),
                "pre_restore_backup_path": str(result.pre_restore_backup_path),
                "db_restored": result.db_restored,
                "workspace_files_restored": result.workspace_files_restored,
                "workspace_replaced": result.workspace_replaced,
            },
        )
