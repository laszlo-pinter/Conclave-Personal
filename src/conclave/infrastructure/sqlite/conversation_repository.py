from datetime import datetime

from conclave.domain.conversation import Conversation
from conclave.domain.participant import Participant, ParticipantType


class SQLiteConversationRepository:
    def __init__(self, connection):
        self._connection = connection

    def save(self, conversation: Conversation) -> None:
        self._connection.execute(
            """
            INSERT INTO conversations (id, status, topic, floor, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status     = excluded.status,
                topic      = excluded.topic,
                floor      = excluded.floor,
                created_at = excluded.created_at
            """,
            (
                conversation.id,
                conversation.status,
                conversation.topic,
                conversation.floor,
                conversation.created_at.isoformat(),
            ),
        )

    def get_by_id(self, conversation_id: str) -> Conversation | None:
        cursor = self._connection.execute(
            """
            SELECT id, status, topic, floor, created_at
            FROM conversations
            WHERE id = ?
            """,
            (conversation_id,),
        )
        row = cursor.fetchone()

        if row is None:
            return None

        conversation = Conversation(
            id=row[0],
            status=row[1],
            topic=row[2] or "",
            floor=row[3],
            created_at=datetime.fromisoformat(row[4]),
            messages=[],
            participants=[],
        )

        participant_cursor = self._connection.execute(
            """
            SELECT id, conversation_id, participant_type, name, created_at
            FROM participants
            WHERE conversation_id = ?
            ORDER BY rowid
            """,
            (conversation_id,),
        )

        for participant_row in participant_cursor.fetchall():
            conversation.participants.append(
                Participant(
                    id=participant_row[0],
                    conversation_id=participant_row[1],
                    participant_type=ParticipantType(participant_row[2]),
                    name=participant_row[3],
                    created_at=datetime.fromisoformat(participant_row[4]),
                )
            )

        return conversation

    def load(self, conversation_id: str):
        return self.get_by_id(conversation_id)

    def list_all(self) -> list[Conversation]:
        rows = self._connection.execute(
            """
            SELECT id, status, topic, floor, created_at
            FROM conversations
            WHERE status <> 'archived'
            ORDER BY created_at DESC
            """
        ).fetchall()

        return [
            Conversation(
                id=row[0],
                status=row[1],
                topic=row[2] or "",
                floor=row[3],
                created_at=datetime.fromisoformat(row[4]),
                messages=[],
                participants=[],
            )
            for row in rows
        ]

    def delete(self, conversation_id: str) -> None:
        self._connection.execute(
            "DELETE FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        )
        self._connection.execute(
            "DELETE FROM participants WHERE conversation_id = ?",
            (conversation_id,),
        )
        self._connection.execute(
            "DELETE FROM conversations WHERE id = ?",
            (conversation_id,),
        )