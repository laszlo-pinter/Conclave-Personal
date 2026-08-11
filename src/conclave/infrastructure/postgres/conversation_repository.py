# src/conclave/infrastructure/postgres/conversation_repository.py

from datetime import datetime

from conclave.domain.conversation import Conversation
from conclave.domain.participant import Participant, ParticipantType


class PostgresConversationRepository:
    def __init__(self, connection) -> None:
        self._connection = connection

    def save(self, conversation: Conversation) -> None:
        with self._connection.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversations (id, status, topic, floor, rules, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    status     = EXCLUDED.status,
                    topic      = EXCLUDED.topic,
                    floor      = EXCLUDED.floor,
                    rules      = EXCLUDED.rules
                """,
                (
                    conversation.id,
                    conversation.status,
                    conversation.topic,
                    conversation.floor,
                    conversation.rules,
                    conversation.created_at,
                ),
            )

    def load(self, conversation_id: str) -> Conversation | None:
        return self.get_by_id(conversation_id)

    def get_by_id(self, conversation_id: str) -> Conversation | None:
        with self._connection.cursor() as cur:
            cur.execute(
                "SELECT id, status, topic, floor, rules, created_at FROM conversations WHERE id = %s",
                (conversation_id,),
            )
            row = cur.fetchone()

        if row is None:
            return None

        conversation = Conversation(
            id=row[0],
            status=row[1],
            topic=row[2] or "",
            floor=row[3],
            rules=row[4] or "",
            created_at=row[5] if isinstance(row[5], datetime) else datetime.fromisoformat(row[5]),
            messages=[],
            participants=[],
        )

        with self._connection.cursor() as cur:
            cur.execute(
                """
                SELECT id, conversation_id, participant_type, name, created_at
                FROM participants WHERE conversation_id = %s ORDER BY created_at
                """,
                (conversation_id,),
            )
            for prow in cur.fetchall():
                conversation.participants.append(
                    Participant(
                        id=prow[0],
                        conversation_id=prow[1],
                        participant_type=ParticipantType(prow[2]),
                        name=prow[3],
                        created_at=prow[4] if isinstance(prow[4], datetime) else datetime.fromisoformat(prow[4]),
                    )
                )

        return conversation

    def list_all(self) -> list[Conversation]:
        with self._connection.cursor() as cur:
            cur.execute(
                "SELECT id, status, topic, floor, rules, created_at FROM conversations "
                "WHERE status <> 'archived' ORDER BY created_at DESC"
            )
            rows = cur.fetchall()

        return [
            Conversation(
                id=row[0],
                status=row[1],
                topic=row[2] or "",
                floor=row[3],
                rules=row[4] or "",
                created_at=row[5] if isinstance(row[5], datetime) else datetime.fromisoformat(row[5]),
                messages=[],
                participants=[],
            )
            for row in rows
        ]

    def delete(self, conversation_id: str) -> None:
        with self._connection.cursor() as cur:
            cur.execute("DELETE FROM messages WHERE conversation_id = %s", (conversation_id,))
            cur.execute("DELETE FROM participants WHERE conversation_id = %s", (conversation_id,))
            cur.execute("DELETE FROM conversations WHERE id = %s", (conversation_id,))
