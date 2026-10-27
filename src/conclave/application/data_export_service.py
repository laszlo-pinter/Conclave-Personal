# src/conclave/application/data_export_service.py

from typing import Any

from conclave.application.conversation_flow import ConversationFlowService


class DataExportService:
    """Exportiert Conversation-Daten als lokale JSON-Artefakte."""

    def __init__(self, flow_service: ConversationFlowService):
        self._flow = flow_service

    @staticmethod
    def _tool_event_to_dict(event) -> dict[str, Any]:
        return {
            "id": event.id,
            "conversation_id": event.conversation_id,
            "message_id": event.message_id,
            "run_id": event.run_id,
            "participant_id": event.participant_id,
            "tool": event.tool,
            "status": event.status,
            "input": event.input_json,
            "output": event.output_json,
            "error": event.error,
            "created_at": event.created_at.isoformat(),
        }

    def export_conversation(self, conversation_id: str) -> dict[str, Any]:
        conversation = self._flow.load_conversation(conversation_id)
        events = self._flow.list_tool_events_by_conversation(conversation_id)
        events_by_message: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            if not event.message_id:
                continue
            events_by_message.setdefault(event.message_id, []).append(self._tool_event_to_dict(event))
        return {
            "id": conversation.id,
            "status": conversation.status,
            "topic": conversation.topic,
            "created_at": conversation.created_at.isoformat(),
            "tool_events": [self._tool_event_to_dict(event) for event in events],
            # Auch Reports fehlgeschlagener Aufrufe (ohne message_id)
            "context_reports": [r.to_dict() for r in self._flow.list_context_reports(conversation_id)],
            "messages": [
                {
                    "id": m.id,
                    "sequence": m.sequence,
                    "author_type": m.author_type.value,
                    "author_id": m.author_id,
                    "content": m.content,
                    "created_at": m.created_at.isoformat(),
                    "tool_events": events_by_message.get(m.id, []),
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
