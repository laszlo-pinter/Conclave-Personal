# tests/infrastructure/sqlite/test_agent_repository.py

import pytest
from conclave.domain.agent import Agent
from conclave.infrastructure.sqlite.agent_repository import SQLiteAgentRepository
from datetime import datetime


def make_agent(**kwargs) -> Agent:
    defaults = dict(id="a1", name="Claude", provider="anthropic", model="claude-sonnet-4-20250514")
    defaults.update(kwargs)
    return Agent(**defaults)


def test_save_and_get_roundtrip(db_connection, crypto):
    repo = SQLiteAgentRepository(db_connection, crypto)
    agent = make_agent(role="analytiker", topic="KI", system_prompt="Sei präzise.")
    repo.save(agent)

    loaded = repo.get("a1")
    assert loaded is not None
    assert loaded.id == "a1"
    assert loaded.name == "Claude"
    assert loaded.role == "analytiker"
    assert loaded.topic == "KI"
    assert loaded.system_prompt == "Sei präzise."
    assert isinstance(loaded.created_at, datetime)


def test_get_unknown_returns_none(db_connection, crypto):
    repo = SQLiteAgentRepository(db_connection, crypto)
    assert repo.get("unbekannt") is None


def test_list_all_empty(db_connection, crypto):
    repo = SQLiteAgentRepository(db_connection, crypto)
    assert repo.list_all() == []


def test_list_all_returns_all(db_connection, crypto):
    repo = SQLiteAgentRepository(db_connection, crypto)
    repo.save(make_agent(id="a1", name="Eins"))
    repo.save(make_agent(id="a2", name="Zwei"))
    repo.save(make_agent(id="a3", name="Drei"))

    result = repo.list_all()
    assert len(result) == 3
    assert {a.id for a in result} == {"a1", "a2", "a3"}


def test_save_updates_existing(db_connection, crypto):
    repo = SQLiteAgentRepository(db_connection, crypto)
    repo.save(make_agent(id="a1", name="Alt"))
    repo.save(make_agent(id="a1", name="Neu", role="kritiker"))

    loaded = repo.get("a1")
    assert loaded.name == "Neu"
    assert loaded.role == "kritiker"
    assert len(repo.list_all()) == 1


def test_delete_removes_agent(db_connection, crypto):
    repo = SQLiteAgentRepository(db_connection, crypto)
    repo.save(make_agent(id="a1"))
    repo.delete("a1")

    assert repo.get("a1") is None


def test_delete_unknown_does_not_raise(db_connection, crypto):
    repo = SQLiteAgentRepository(db_connection, crypto)
    repo.delete("unbekannt")


def test_list_ordered_by_created_at(db_connection, crypto):
    from datetime import timezone, timedelta
    repo = SQLiteAgentRepository(db_connection, crypto)
    t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 2, tzinfo=timezone.utc)
    repo.save(Agent(id="b", name="B", provider="anthropic", model="m", created_at=t2))
    repo.save(Agent(id="a", name="A", provider="anthropic", model="m", created_at=t1))

    result = repo.list_all()
    assert result[0].id == "a"
    assert result[1].id == "b"


# ── API-Key-Verschlüsselung ────────────────────────────────────────────────

def test_save_and_get_roundtrip_with_api_key(db_connection):
    """api_key wird verschlüsselt gespeichert und entschlüsselt gelesen."""
    from cryptography.fernet import Fernet
    from conclave.infrastructure.crypto import CryptoService

    key = Fernet.generate_key()
    crypto = CryptoService(key)
    repo = SQLiteAgentRepository(db_connection, crypto)

    agent = make_agent(api_key="sk-ant-secret-123")
    repo.save(agent)

    loaded = repo.get("a1")
    assert loaded.api_key == "sk-ant-secret-123"


def test_api_key_is_not_stored_in_plaintext(db_connection):
    """Der Klartext-Key darf nicht direkt in der DB stehen."""
    from cryptography.fernet import Fernet
    from conclave.infrastructure.crypto import CryptoService

    key = Fernet.generate_key()
    crypto = CryptoService(key)
    repo = SQLiteAgentRepository(db_connection, crypto)

    repo.save(make_agent(api_key="sk-ant-geheimnis"))

    raw = db_connection.execute(
        "SELECT api_key_enc FROM agents WHERE id = 'a1'"
    ).fetchone()
    assert raw is not None
    assert "sk-ant-geheimnis" not in raw[0], "API-Key steht im Klartext in der DB!"


def test_empty_api_key_roundtrip(db_connection):
    """Leerer api_key bleibt nach Roundtrip leer."""
    from cryptography.fernet import Fernet
    from conclave.infrastructure.crypto import CryptoService

    crypto = CryptoService(Fernet.generate_key())
    repo = SQLiteAgentRepository(db_connection, crypto)

    repo.save(make_agent(api_key=""))
    loaded = repo.get("a1")
    assert loaded.api_key == ""
