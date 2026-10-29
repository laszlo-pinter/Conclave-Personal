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
    monkeypatch.setenv("CONCLAVE_API_TOKEN_FILE", str(tmp_path / "api.token"))
    monkeypatch.setenv("CONCLAVE_AGENT_TOKEN_FILE", str(tmp_path / "agent.token"))
    monkeypatch.delenv("CONCLAVE_AGENT_KEY", raising=False)
    monkeypatch.setenv("CONCLAVE_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("CONCLAVE_CONFIG_FILE", str(tmp_path / "config.toml"))
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(tmp_path / "workspace"))


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


# Beispiel-Export eines Boards (Aufbau der JSON-Ausgabe eines Board-Exports, B3)
BOARD_SAMPLE_EXPORT = {
    "exported_at": "2026-10-29T17:39:07Z",
    "statuses": ["todo", "doing", "review", "done"],
    "projects": [{
        "id": 1, "slug": "conclave", "name": "conclave", "repos": ["x/y"], "color": None,
        "created_at": "2026-10-28T16:08:38Z", "open": 2, "total": 3,
        "tasks": [
            {"id": 7, "key": "conclave#7", "title": "Z2", "description": "## Ziel\nRechte", "tags": ["zugaenge"],
             "human": False, "images": [], "status": "done", "created_at": "2026-10-28T18:51:00Z",
             "updated_at": "2026-10-28T20:00:00Z",
             "comments": [
                 {"id": "2", "task_id": "7", "author": "CD · auto-review", "body": "in Ordnung",
                  "created_at": "2026-10-28T19:56:00Z"},
                 {"id": "1", "task_id": "7", "author": "cc", "body": "fertig", "created_at": "2026-10-28T19:55:00Z"}]},
            {"id": 13, "key": "conclave#13", "title": "Migrations-Runner", "description": "", "tags": [],
             "human": True, "images": [], "status": "todo", "created_at": "2026-10-28T23:09:28Z",
             "updated_at": "2026-10-28T23:09:28Z", "comments": []},
            {"id": 2, "key": "conclave#2", "title": "E1", "description": "Frage", "tags": ["entscheidung"],
             "human": True, "images": [], "status": "done", "created_at": "2026-10-28T18:50:00Z",
             "updated_at": "2026-10-28T19:00:00Z", "comments": [
                 {"id": "3", "task_id": "2", "author": "me", "body": "(a)", "created_at": "2026-10-28T19:00:00Z"}]},
        ],
    }],
}


@pytest.fixture
def board_sample_export():
    """Frische Kopie je Test, damit Tests den Export veraendern duerfen."""
    import copy
    return copy.deepcopy(BOARD_SAMPLE_EXPORT)
