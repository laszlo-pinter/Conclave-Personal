# tests/infrastructure/sqlite/test_unit_of_work.py

import pytest

from conclave.infrastructure.sqlite.unit_of_work import SQLiteUnitOfWork


def test_unit_of_work_commits_on_success(db_connection):
    with SQLiteUnitOfWork(db_connection) as uow:
        uow.connection.execute(
            "INSERT INTO conversations (id, status, created_at) VALUES (?, ?, ?)",
            ("conv-1", "active", "2026-01-01T00:00:00"),
        )

    row = db_connection.execute(
        "SELECT id FROM conversations WHERE id = ?", ("conv-1",)
    ).fetchone()
    assert row is not None


def test_unit_of_work_rolls_back_on_exception(db_connection):
    with pytest.raises(ValueError):
        with SQLiteUnitOfWork(db_connection) as uow:
            uow.connection.execute(
                "INSERT INTO conversations (id, status, created_at) VALUES (?, ?, ?)",
                ("conv-2", "active", "2026-01-01T00:00:00"),
            )
            raise ValueError("simulated failure")

    row = db_connection.execute(
        "SELECT id FROM conversations WHERE id = ?", ("conv-2",)
    ).fetchone()
    assert row is None


def test_unit_of_work_provides_repositories(db_connection):
    with SQLiteUnitOfWork(db_connection) as uow:
        assert uow.conversations is not None
        assert uow.messages is not None
        assert uow.participants is not None


def test_repository_save_inside_uow_does_not_commit_independently(db_connection):
    """Ein Repository-save() innerhalb einer UoW darf keinen eigenen Commit auslösen.
    Bei anschließender Exception muss der Rollback greifen.
    """
    from conclave.domain.conversation import Conversation
    from datetime import datetime, UTC
    import uuid

    conv_id = str(uuid.uuid4())
    conv = Conversation(
        id=conv_id,
        status="active",
        topic="test",
        floor=None,
        created_at=datetime.now(UTC),
        messages=[],
        participants=[],
    )

    try:
        with SQLiteUnitOfWork(db_connection) as uow:
            uow.conversations.save(conv)          # würde selbst committen wenn Bug vorhanden
            raise RuntimeError("Fehler nach save")
    except RuntimeError:
        pass

    row = db_connection.execute(
        "SELECT id FROM conversations WHERE id = ?", (conv_id,)
    ).fetchone()
    assert row is None, (
        "Repository hat innerhalb der UoW selbstständig committed – "
        "Rollback konnte Teilzustand nicht rückgängig machen."
    )


def test_message_save_inside_uow_does_not_commit_independently(db_connection):
    """SQLiteMessageRepository.save() darf innerhalb einer UoW nicht selbst committen."""
    from conclave.domain.conversation import Conversation
    from conclave.domain.message import Message, MessageAuthorType
    from datetime import datetime, UTC
    import uuid

    conv_id = str(uuid.uuid4())
    msg_id = str(uuid.uuid4())
    now = datetime.now(UTC)

    # Conversation direkt einfügen (außerhalb UoW, korrekt committed)
    db_connection.execute(
        "INSERT INTO conversations (id, status, topic, created_at) VALUES (?, ?, ?, ?)",
        (conv_id, "active", "", now.isoformat()),
    )
    db_connection.commit()

    msg = Message(
        id=msg_id,
        conversation_id=conv_id,
        author_type=MessageAuthorType.USER,
        author_id=None,
        content="Testnachricht",
        sequence=1,
        created_at=now,
    )

    try:
        with SQLiteUnitOfWork(db_connection) as uow:
            uow.messages.save(msg)
            raise RuntimeError("Fehler nach message save")
    except RuntimeError:
        pass

    row = db_connection.execute(
        "SELECT id FROM messages WHERE id = ?", (msg_id,)
    ).fetchone()
    assert row is None, (
        "SQLiteMessageRepository hat innerhalb UoW selbstständig committed."
    )


def test_unit_of_work_rollback_leaves_no_partial_state(db_connection):
    """Wenn eine Operation mittendrin fehlschlägt, darf kein Teilzustand übrig bleiben."""
    from conclave.domain.conversation import Conversation
    from conclave.domain.message import Message, MessageAuthorType
    import uuid
    from datetime import datetime, UTC

    conversation_id = str(uuid.uuid4())

    try:
        with SQLiteUnitOfWork(db_connection) as uow:
            uow.connection.execute(
                "INSERT INTO conversations (id, status, created_at) VALUES (?, ?, ?)",
                (conversation_id, "active", "2026-01-01T00:00:00"),
            )
            # Zweite Operation schlägt fehl
            raise RuntimeError("Fehler nach erstem Write")
    except RuntimeError:
        pass

    row = db_connection.execute(
        "SELECT id FROM conversations WHERE id = ?", (conversation_id,)
    ).fetchone()
    assert row is None, "Rollback hat keinen Teilzustand hinterlassen"
