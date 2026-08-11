import sqlite3

import pytest
from cryptography.fernet import Fernet

from conclave.application.conversation_flow import ConversationFlowService
from conclave.infrastructure.crypto import CryptoService
from conclave.infrastructure.sqlite.conversation_repository import SQLiteConversationRepository
from conclave.infrastructure.sqlite.message_repository import SQLiteMessageRepository
from conclave.infrastructure.sqlite.participant_repository import SQLiteParticipantRepository
from conclave.infrastructure.sqlite.schema import initialize_schema


@pytest.fixture
def db_connection():
    connection = sqlite3.connect(":memory:")
    initialize_schema(connection)
    yield connection
    connection.close()


@pytest.fixture
def crypto() -> CryptoService:
    """CryptoService mit frisch generiertem Schlüssel für Tests."""
    return CryptoService(Fernet.generate_key())


@pytest.fixture(autouse=True)
def isolated_secret_key(monkeypatch, tmp_path):
    """Verhindert, dass Tests Secret-Key-Dateien im Benutzerprofil anlegen."""
    monkeypatch.setenv("CONCLAVE_SECRET_KEY_FILE", str(tmp_path / "secret.key"))


@pytest.fixture
def agent_service(db_connection, crypto):
    """AgentService mit In-Memory-DB und Test-CryptoService."""
    from conclave.application.agent_service import AgentService
    from conclave.infrastructure.sqlite.agent_repository import SQLiteAgentRepository
    repo = SQLiteAgentRepository(db_connection, crypto)
    return AgentService(repo)


@pytest.fixture
def service(db_connection):
    return ConversationFlowService(
        conversation_repository=SQLiteConversationRepository(db_connection),
        message_repository=SQLiteMessageRepository(db_connection),
        participant_repository=SQLiteParticipantRepository(db_connection),
    )
