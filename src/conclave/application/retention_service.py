# src/conclave/application/retention_service.py

from datetime import datetime, timezone, timedelta

from conclave.application.conversation_flow import ConversationFlowService
from conclave.infrastructure.log import get_logger

logger = get_logger("application.retention")


class RetentionService:
    """Loescht Conversations nach lokaler Aufbewahrungsfrist."""

    def __init__(self, flow_service: ConversationFlowService):
        self._flow = flow_service

    def purge_expired(self, retention_days: int, dry_run: bool = False) -> list[str]:
        """Loescht Conversations aelter als retention_days. Gibt IDs zurueck."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        conversations = self._flow.list_conversations()

        expired_ids = [
            c.id for c in conversations
            if c.created_at < cutoff
        ]

        if dry_run:
            logger.info("Retention dry-run: %d conversations wuerden geloescht", len(expired_ids))
            return expired_ids

        for conv_id in expired_ids:
            self._flow.delete_conversation(conv_id)

        if expired_ids:
            logger.info("Retention: %d conversations geloescht", len(expired_ids))

        return expired_ids
