# src/conclave/infrastructure/postgres/participant_repository.py

from datetime import datetime

from conclave.domain.participant import Participant, ParticipantType


class PostgresParticipantRepository:
    def __init__(self, connection) -> None:
        self._connection = connection

    def save(self, participant: Participant) -> None:
        with self._connection.cursor() as cur:
            cur.execute(
                """
                INSERT INTO participants
                    (id, conversation_id, participant_type, name, created_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (conversation_id, id) DO NOTHING
                """,
                (
                    participant.id,
                    participant.conversation_id,
                    participant.participant_type.value,
                    participant.name,
                    participant.created_at,
                ),
            )

    def list_by_conversation_id(self, conversation_id: str) -> list[Participant]:
        with self._connection.cursor() as cur:
            cur.execute(
                """
                SELECT id, conversation_id, participant_type, name, created_at
                FROM participants WHERE conversation_id = %s ORDER BY created_at, id
                """,
                (conversation_id,),
            )
            rows = cur.fetchall()

        return [
            Participant(
                id=row[0],
                conversation_id=row[1],
                participant_type=ParticipantType(row[2]),
                name=row[3],
                created_at=row[4] if isinstance(row[4], datetime) else datetime.fromisoformat(row[4]),
            )
            for row in rows
        ]

    def delete_by_conversation(self, conversation_id: str) -> None:
        with self._connection.cursor() as cur:
            cur.execute(
                "DELETE FROM participants WHERE conversation_id = %s",
                (conversation_id,),
            )

    def delete(self, conversation_id: str, participant_id: str) -> None:
        with self._connection.cursor() as cur:
            cur.execute(
                "DELETE FROM participants WHERE conversation_id = %s AND id = %s",
                (conversation_id, participant_id),
            )
