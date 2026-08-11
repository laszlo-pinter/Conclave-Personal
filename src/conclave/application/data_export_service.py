# src/conclave/application/data_export_service.py

from typing import Any

from conclave.application.conversation_flow import ConversationFlowService


class DataExportService:
    """Exportiert Conversation-Daten als lokale JSON-Artefakte."""

    def __init__(self, flow_service: ConversationFlowService):
        self._flow = flow_service

    def export_conversation(self, conversation_id: str) -> dict[str, Any]:
        conversation = self._flow.load_conversation(conversation_id)
        return {
            "id": conversation.id,
            "status": conversation.status,
            "topic": conversation.topic,
            "created_at": conversation.created_at.isoformat(),
            "messages": [
                {
                    "id": m.id,
                    "sequence": m.sequence,
                    "author_type": m.author_type.value,
                    "author_id": m.author_id,
                    "content": m.content,
                    "created_at": m.created_at.isoformat(),
                }
                for m in conversation.messages
            ],
            "participants": [
                {
                    "id": p.id,
                    "name": p.name,
                    "type": p.participant_type.value,
                    "created_at": p.created_at.isoformat(),
                }
                for p in conversation.participants
            ],
        }
