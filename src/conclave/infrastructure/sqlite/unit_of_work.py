# src/conclave/infrastructure/sqlite/unit_of_work.py

import sqlite3

from conclave.infrastructure.sqlite.conversation_repository import SQLiteConversationRepository
from conclave.infrastructure.sqlite.message_repository import SQLiteMessageRepository
from conclave.infrastructure.sqlite.participant_repository import SQLiteParticipantRepository


class SQLiteUnitOfWork:
    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection
        # Repositories direkt im __init__ setzen, damit isinstance(uow, UnitOfWork) funktioniert
        self.conversations = SQLiteConversationRepository(connection)
        self.messages = SQLiteMessageRepository(connection)
        self.participants = SQLiteParticipantRepository(connection)

    def __enter__(self) -> "SQLiteUnitOfWork":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is None:
            self._connection.commit()
        else:
            self._connection.rollback()
        return False

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection
