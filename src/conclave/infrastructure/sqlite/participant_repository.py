from datetime import datetime

from conclave.domain.participant import Participant, ParticipantType


class SQLiteParticipantRepository:
    def __init__(self, connection):
        self._connection = connection

    def save(self, participant: Participant) -> None:
        self._connection.execute(
            """
            INSERT INTO participants (
                id,
                conversation_id,
                participant_type,
                name,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                participant.id,
                participant.conversation_id,
                participant.participant_type.value,
                participant.name,
                participant.created_at.isoformat(),
            ),
        )

    def delete_by_conversation(self, conversation_id: str) -> None:
        self._connection.execute(
            "DELETE FROM participants WHERE conversation_id = ?",
            (conversation_id,),
        )

    def delete(self, conversation_id: str, participant_id: str) -> None:
        self._connection.execute(
            "DELETE FROM participants WHERE conversation_id = ? AND id = ?",
            (conversation_id, participant_id),
        )

    def list_by_conversation_id(self, conversation_id: str) -> list[Participant]:
        rows = self._connection.execute(
            """
            SELECT
                id,
                conversation_id,
                participant_type,
                name,
                created_at
            FROM participants
            WHERE conversation_id = ?
            ORDER BY created_at, id
            """,
            (conversation_id,),
        ).fetchall()

        participants = []
        for row in rows:
            participants.append(
                Participant(
                    id=row[0],
                    conversation_id=row[1],
                    participant_type=ParticipantType(row[2]),
                    name=row[3],
                    created_at=datetime.fromisoformat(row[4]),
                )
            )
        return participants
