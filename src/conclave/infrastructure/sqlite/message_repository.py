# src/conclave/infrastructure/sqlite/message_repository.py

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from conclave.domain.message import Message, MessageAuthorType

if TYPE_CHECKING:
    from conclave.infrastructure.crypto import CryptoService


class SQLiteMessageRepository:
    def __init__(self, connection, crypto: CryptoService | None = None):
        self._connection = connection
        self._crypto = crypto

    def _encrypt(self, plaintext: str) -> str:
        if self._crypto is None:
            return plaintext
        return self._crypto.encrypt(plaintext)

    def _decrypt(self, ciphertext: str) -> str:
        if self._crypto is None:
            return ciphertext
        return self._crypto.decrypt(ciphertext)

    def save(self, message: Message) -> None:
        # Atomare Sequence: MAX+1 in der DB statt len(messages)+1 im Speicher
        cursor = self._connection.execute(
            """
            INSERT INTO messages (
                id, conversation_id, author_type, author_id, content, sequence, created_at
            )
            VALUES (?, ?, ?, ?, ?,
                COALESCE((SELECT MAX(sequence) FROM messages WHERE conversation_id = ?), 0) + 1,
                ?)
            """,
            (
                message.id,
                message.conversation_id,
                message.author_type.value,
                message.author_id,
                self._encrypt(message.content),
                message.conversation_id,
                message.created_at.isoformat(),
            ),
        )
        # Gesetzte Sequence zuruecklesen
        row = self._connection.execute(
            "SELECT sequence FROM messages WHERE id = ?", (message.id,)
        ).fetchone()
        if row:
            message.sequence = row[0]

    def list_by_conversation_id(self, conversation_id: str) -> list[Message]:
        rows = self._connection.execute(
            """
            SELECT
                id,
                conversation_id,
                author_type,
                author_id,
                content,
                sequence,
                created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY sequence
            """,
            (conversation_id,),
        ).fetchall()

        messages = []
        for row in rows:
            messages.append(
                Message(
                    id=row[0],
                    conversation_id=row[1],
                    author_type=MessageAuthorType(row[2]),
                    author_id=row[3],
                    content=self._decrypt(row[4]),
                    sequence=row[5],
                    created_at=datetime.fromisoformat(row[6]),
                )
            )
        return messages