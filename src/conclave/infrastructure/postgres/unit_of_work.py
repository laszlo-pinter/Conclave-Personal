# src/conclave/infrastructure/postgres/unit_of_work.py

try:
    import psycopg2
except ImportError:
    raise ImportError(
        "Das 'psycopg2'-Paket ist nicht installiert. "
        "Bitte installieren mit: pip install conclave[postgres]"
    )

from conclave.infrastructure.postgres.conversation_repository import PostgresConversationRepository
from conclave.infrastructure.postgres.message_repository import PostgresMessageRepository
from conclave.infrastructure.postgres.participant_repository import PostgresParticipantRepository


class PostgresUnitOfWork:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._connection = None
        # Lazy-Init der Repositories – werden in __enter__ gesetzt,
        # aber als None vorinitialisiert damit isinstance(uow, UnitOfWork) funktioniert
        self.conversations: PostgresConversationRepository | None = None
        self.messages: PostgresMessageRepository | None = None
        self.participants: PostgresParticipantRepository | None = None

    def __enter__(self) -> "PostgresUnitOfWork":
        self._connection = psycopg2.connect(self._dsn)
        self._connection.autocommit = False
        self.conversations = PostgresConversationRepository(self._connection)
        self.messages = PostgresMessageRepository(self._connection)
        self.participants = PostgresParticipantRepository(self._connection)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if self._connection is None:
            return False
        try:
            if exc_type is None:
                self._connection.commit()
            else:
                self._connection.rollback()
        finally:
            self._connection.close()
            self._connection = None
        return False
