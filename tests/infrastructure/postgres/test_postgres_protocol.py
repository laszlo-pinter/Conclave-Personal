# tests/infrastructure/postgres/test_postgres_protocol.py
"""
Prüft, dass PostgreSQL-Repositories die korrekten Protokolle erfüllen
und die UnitOfWork korrekt strukturiert ist.
Läuft ohne echte PostgreSQL-Instanz (nur Protokoll-Checks mit Mocks).
"""

import pytest
from unittest.mock import MagicMock, patch


# ── UnitOfWork Protocol ────────────────────────────────────────────────────

def test_uow_protocol_exists():
    from conclave.application.ports import UnitOfWork
    assert UnitOfWork is not None


def test_sqlite_uow_satisfies_protocol():
    from conclave.application.ports import UnitOfWork
    from conclave.infrastructure.sqlite.unit_of_work import SQLiteUnitOfWork
    import sqlite3
    from conclave.infrastructure.sqlite.schema import initialize_schema

    conn = sqlite3.connect(":memory:")
    initialize_schema(conn)
    uow = SQLiteUnitOfWork(conn)
    assert isinstance(uow, UnitOfWork)


def test_postgres_uow_satisfies_protocol():
    psycopg2 = pytest.importorskip("psycopg2")
    from conclave.application.ports import UnitOfWork
    from conclave.infrastructure.postgres.unit_of_work import PostgresUnitOfWork

    mock_conn = MagicMock()
    with patch("psycopg2.connect", return_value=mock_conn):
        uow = PostgresUnitOfWork(dsn="postgresql://test")
        with patch.object(uow, "_connection", mock_conn):
            assert isinstance(uow, UnitOfWork)


# ── PostgreSQL Repositories implementieren die richtigen Protocols ─────────

def test_postgres_conversation_repository_satisfies_protocol():
    pytest.importorskip("psycopg2")
    from conclave.application.ports import ConversationRepository
    from conclave.infrastructure.postgres.conversation_repository import PostgresConversationRepository

    repo = PostgresConversationRepository(MagicMock())
    assert isinstance(repo, ConversationRepository)


def test_postgres_message_repository_satisfies_protocol():
    pytest.importorskip("psycopg2")
    from conclave.application.ports import MessageRepository
    from conclave.infrastructure.postgres.message_repository import PostgresMessageRepository

    repo = PostgresMessageRepository(MagicMock())
    assert isinstance(repo, MessageRepository)


def test_postgres_participant_repository_satisfies_protocol():
    pytest.importorskip("psycopg2")
    from conclave.application.ports import ParticipantRepository
    from conclave.infrastructure.postgres.participant_repository import PostgresParticipantRepository

    repo = PostgresParticipantRepository(MagicMock())
    assert isinstance(repo, ParticipantRepository)


def test_postgres_agent_repository_satisfies_protocol():
    pytest.importorskip("psycopg2")
    from conclave.application.ports import AgentRepository
    from conclave.infrastructure.postgres.agent_repository import PostgresAgentRepository
    from conclave.infrastructure.crypto import CryptoService
    from cryptography.fernet import Fernet

    crypto = CryptoService(Fernet.generate_key())
    repo = PostgresAgentRepository(MagicMock(), crypto)
    assert isinstance(repo, AgentRepository)
