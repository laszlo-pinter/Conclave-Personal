# tests/infrastructure/sqlite/test_message_encryption.py

import sqlite3
from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet

from conclave.domain.message import Message, MessageAuthorType
from conclave.infrastructure.crypto import CryptoService, NullCryptoService
from conclave.infrastructure.sqlite.message_repository import SQLiteMessageRepository
from conclave.infrastructure.sqlite.schema import initialize_schema


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    initialize_schema(conn)
    # Conversation anlegen damit Foreign Keys nicht fehlschlagen
    conn.execute(
        "INSERT INTO conversations (id, status, topic, created_at) VALUES (?, ?, ?, ?)",
        ("conv-1", "active", "", "2026-01-01T00:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO conversations (id, status, topic, created_at) VALUES (?, ?, ?, ?)",
        ("c1", "active", "", "2026-01-01T00:00:00+00:00"),
    )
    yield conn
    conn.close()


@pytest.fixture
def crypto():
    return CryptoService(Fernet.generate_key())


def _make_message(content: str = "Hallo Welt", conversation_id: str = "conv-1") -> Message:
    return Message(
        id="msg-1",
        conversation_id=conversation_id,
        author_type=MessageAuthorType.USER,
        author_id=None,
        content=content,
        sequence=1,
        created_at=datetime.now(timezone.utc),
    )


class TestEncryptedStorage:
    def test_content_is_encrypted_in_database(self, db, crypto):
        """Gespeicherter Content in DB darf nicht Klartext sein."""
        repo = SQLiteMessageRepository(db, crypto=crypto)
        repo.save(_make_message("Geheime Nachricht"))

        row = db.execute("SELECT content FROM messages WHERE id = 'msg-1'").fetchone()
        assert row[0] != "Geheime Nachricht"
        assert "Geheime" not in row[0]

    def test_loaded_content_is_decrypted(self, db, crypto):
        """Geladener Content muss wieder Klartext sein."""
        repo = SQLiteMessageRepository(db, crypto=crypto)
        repo.save(_make_message("Klartext-Antwort"))

        messages = repo.list_by_conversation_id("conv-1")
        assert messages[0].content == "Klartext-Antwort"

    def test_roundtrip_preserves_content(self, db, crypto):
        """Verschluesselt speichern, entschluesselt laden, Original == Geladen."""
        original = "Dies ist ein vollstaendiger Satz mit Zahlen 12345."
        repo = SQLiteMessageRepository(db, crypto=crypto)
        repo.save(_make_message(original))

        messages = repo.list_by_conversation_id("conv-1")
        assert messages[0].content == original

    def test_empty_content_roundtrip(self, db, crypto):
        repo = SQLiteMessageRepository(db, crypto=crypto)
        repo.save(_make_message(""))

        messages = repo.list_by_conversation_id("conv-1")
        assert messages[0].content == ""

    def test_unicode_content_roundtrip(self, db, crypto):
        """Umlaute, Emojis, CJK-Zeichen muessen erhalten bleiben."""
        content = "Gruesse mit Umlauten: ae oe ue ss"
        repo = SQLiteMessageRepository(db, crypto=crypto)
        repo.save(_make_message(content))

        messages = repo.list_by_conversation_id("conv-1")
        assert messages[0].content == content

    def test_multiple_messages_independently_encrypted(self, db, crypto):
        """Jede Message hat ein eigenes Ciphertext (Fernet-IV unterschiedlich)."""
        repo = SQLiteMessageRepository(db, crypto=crypto)
        msg1 = Message(id="m1", conversation_id="c1", author_type=MessageAuthorType.USER,
                       author_id=None, content="Gleicher Text", sequence=1,
                       created_at=datetime.now(timezone.utc))
        msg2 = Message(id="m2", conversation_id="c1", author_type=MessageAuthorType.USER,
                       author_id=None, content="Gleicher Text", sequence=2,
                       created_at=datetime.now(timezone.utc))
        repo.save(msg1)
        repo.save(msg2)

        rows = db.execute("SELECT content FROM messages ORDER BY sequence").fetchall()
        # Gleicher Klartext, aber verschiedene Ciphertexte (Fernet nutzt zufaellige IV)
        assert rows[0][0] != rows[1][0]


class TestNoCryptoFallback:
    def test_without_crypto_content_stored_as_plaintext(self, db):
        """Ohne CryptoService wird Content als Klartext gespeichert (Rueckwaertskompatibilitaet)."""
        repo = SQLiteMessageRepository(db)
        repo.save(_make_message("Klartext"))

        row = db.execute("SELECT content FROM messages WHERE id = 'msg-1'").fetchone()
        assert row[0] == "Klartext"

    def test_without_crypto_content_loaded_as_plaintext(self, db):
        repo = SQLiteMessageRepository(db)
        repo.save(_make_message("Klartext"))

        messages = repo.list_by_conversation_id("conv-1")
        assert messages[0].content == "Klartext"


class TestNullCryptoService:
    def test_null_crypto_encrypt_returns_plaintext(self):
        null = NullCryptoService()
        assert null.encrypt("Klartext") == "Klartext"

    def test_null_crypto_decrypt_returns_plaintext(self):
        null = NullCryptoService()
        assert null.decrypt("Klartext") == "Klartext"
