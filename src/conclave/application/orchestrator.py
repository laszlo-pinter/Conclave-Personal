# src/conclave/application/orchestrator.py

import asyncio
import dataclasses
from dataclasses import dataclass, field

from conclave.application.conversation_flow import ConversationFlowService
from conclave.domain.conversation import Conversation
from conclave.domain.errors import AdapterNotFound, ConversationNotFound
from conclave.infrastructure.log import get_logger

logger = get_logger("application.orchestrator")


@dataclass
class ParticipantResponse:
    participant_id: str
    content: str
    sequence: int


@dataclass
class OrchestratorResult:
    success: bool
    responses: list[ParticipantResponse] = field(default_factory=list)
    error: str = ""


class Orchestrator:
    """Ruft mehrere Participants in einer definierten Reihenfolge auf.

    Jeder Participant sieht die Antworten aller vorherigen – einschließlich
    der anderen Modelle im selben Durchlauf.
    """

    def __init__(self, service: ConversationFlowService):
        self._service = service

    def run(
        self,
        conversation_id: str,
        sequence: list[str],
    ) -> OrchestratorResult:
        responses: list[ParticipantResponse] = []

        logger.info("Orchestrator run: %d participants", len(sequence),
                    extra={"conversation_id": conversation_id})
        for participant_id in sequence:
            try:
                updated = self._service.invoke_participant(
                    conversation_id=conversation_id,
                    participant_id=participant_id,
                )
            except ConversationNotFound:
                return OrchestratorResult(
                    success=False,
                    responses=responses,
                    error=f"Conversation '{conversation_id}' nicht gefunden.",
                )
            except AdapterNotFound:
                return OrchestratorResult(
                    success=False,
                    responses=responses,
                    error=f"Kein Adapter für Participant '{participant_id}' registriert.",
                )

            last_message = updated.messages[-1]
            responses.append(
                ParticipantResponse(
                    participant_id=participant_id,
                    content=last_message.content,
                    sequence=last_message.sequence,
                )
            )

        return OrchestratorResult(success=True, responses=responses)


class ParallelOrchestrator:
    """Ruft Participants in Gruppen auf — innerhalb einer Gruppe parallel, Gruppen sequentiell.

    Jede Gruppe wird parallel via asyncio.gather ausgeführt.
    Gruppen untereinander sind sequentiell, sodass spätere Gruppen
    die Antworten früherer Gruppen sehen.
    """

    def __init__(self, service: ConversationFlowService):
        self._service = service

    async def run(
        self,
        conversation_id: str,
        groups: list[list[str]],
    ) -> OrchestratorResult:
        responses: list[ParticipantResponse] = []
        logger.info("ParallelOrchestrator run: %d groups", len(groups),
                     extra={"conversation_id": conversation_id})

        for group in groups:
            try:
                conversation = self._service.load_conversation(conversation_id)
            except ConversationNotFound:
                return OrchestratorResult(
                    success=False,
                    responses=responses,
                    error=f"Conversation '{conversation_id}' nicht gefunden.",
                )
            snapshot = self._build_group_snapshot(conversation)
            results = await asyncio.gather(
                *(self._complete_one(conversation_id, pid, conversation, snapshot) for pid in group),
                return_exceptions=True,
            )

            has_error = False
            error_msg = ""
            for pid, result in zip(group, results):
                if isinstance(result, Exception):
                    has_error = True
                    error_msg = f"Fehler bei Participant '{pid}': {result}"
                    logger.error(error_msg, extra={"conversation_id": conversation_id})
                else:
                    updated = self._service.add_model_message(
                        conversation_id=conversation_id,
                        participant_id=pid,
                        content=result,
                    )
                    last_message = updated.messages[-1]
                    responses.append(
                        ParticipantResponse(
                            participant_id=pid,
                            content=last_message.content,
                            sequence=last_message.sequence,
                        )
                    )

            if has_error:
                return OrchestratorResult(
                    success=False,
                    responses=responses,
                    error=error_msg,
                )

        return OrchestratorResult(success=True, responses=responses)

    @staticmethod
    def _build_group_snapshot(conversation: Conversation) -> Conversation:
        return dataclasses.replace(
            conversation,
            messages=list(conversation.messages),
            participants=list(conversation.participants),
        )

    async def _complete_one(
        self,
        conversation_id: str,
        participant_id: str,
        conversation: Conversation,
        snapshot: Conversation,
    ) -> str:
        return await self._service.async_complete_participant(
            conversation_id=conversation_id,
            participant_id=participant_id,
            conversation=conversation,
            snapshot=snapshot,
        )
