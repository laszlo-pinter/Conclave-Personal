# tests/infrastructure/sqlite/test_conversation_repository.py

from conclave.domain.conversation import Conversation
from conclave.infrastructure.sqlite.conversation_repository import (
    SQLiteConversationRepository,
)

from conclave.domain.conversation import Conversation
from conclave.infrastructure.sqlite.conversation_repository import SQLiteConversationRepository

def test_load_returns_none_for_unknown_conversation(db_connection):
    repository = SQLiteConversationRepository(db_connection)

    loaded = repository.load("11111111-1111-1111-1111-111111111111")

    assert loaded is None
    
def test_save_and_load_roundtrip_conversation(db_connection):
    repository = SQLiteConversationRepository(db_connection)

    conversation = Conversation.create()

    repository.save(conversation)
    loaded = repository.load(conversation.id)

    assert loaded is not None
    assert loaded.id == conversation.id
    assert loaded.status == conversation.status
    assert loaded.messages == []
    assert loaded.participants == []

def test_conversation_repository_saves_and_loads_conversation(db_connection):
    repository = SQLiteConversationRepository(db_connection)
    conversation = Conversation.create()

    repository.save(conversation)
    loaded = repository.get_by_id(conversation.id)

    assert loaded is not None
    assert loaded.id == conversation.id
    assert loaded.status == "active"
    assert loaded.created_at == conversation.created_at
    assert loaded.messages == []

# ── list_all ───────────────────────────────────────────────────────────────

def test_list_all_returns_empty_when_no_conversations(db_connection):
    repository = SQLiteConversationRepository(db_connection)
    result = repository.list_all()
    assert result == []


def test_list_all_returns_all_conversations(db_connection):
    repository = SQLiteConversationRepository(db_connection)

    conv_a = Conversation.create()
    conv_b = Conversation.create()
    repository.save(conv_a)
    repository.save(conv_b)

    result = repository.list_all()

    assert len(result) == 2
    ids = {c.id for c in result}
    assert conv_a.id in ids
    assert conv_b.id in ids


def test_list_all_returns_conversations_ordered_by_created_at_desc(db_connection):
    from datetime import UTC, datetime, timedelta

    repository = SQLiteConversationRepository(db_connection)

    older = Conversation(
        id="older",
        created_at=datetime.now(UTC) - timedelta(hours=1),
    )
    newer = Conversation(
        id="newer",
        created_at=datetime.now(UTC),
    )
    repository.save(older)
    repository.save(newer)

    result = repository.list_all()

    assert result[0].id == "newer"
    assert result[1].id == "older"


# ── delete ─────────────────────────────────────────────────────────────────

def test_delete_removes_conversation(db_connection):
    repository = SQLiteConversationRepository(db_connection)
    conversation = Conversation.create()
    repository.save(conversation)

    repository.delete(conversation.id)

    assert repository.load(conversation.id) is None


def test_delete_also_removes_messages(db_connection):
    from conclave.infrastructure.sqlite.message_repository import SQLiteMessageRepository

    conv_repo = SQLiteConversationRepository(db_connection)
    msg_repo = SQLiteMessageRepository(db_connection)

    conversation = Conversation.create()
    conv_repo.save(conversation)
    message = conversation.add_user_message("Hallo")
    msg_repo.save(message)

    conv_repo.delete(conversation.id)

    messages = msg_repo.list_by_conversation_id(conversation.id)
    assert messages == []


def test_delete_also_removes_participants(db_connection):
    from conclave.infrastructure.sqlite.participant_repository import SQLiteParticipantRepository
    from conclave.domain.participant import Participant, ParticipantType

    conv_repo = SQLiteConversationRepository(db_connection)
    part_repo = SQLiteParticipantRepository(db_connection)

    conversation = Conversation.create()
    participant = Participant(
        id="p1",
        conversation_id=conversation.id,
        participant_type=ParticipantType.MODEL,
        name="Claude",
    )
    conversation.add_participant(participant)
    conv_repo.save(conversation)

    conv_repo.delete(conversation.id)

    participants = part_repo.list_by_conversation_id(conversation.id)
    assert participants == []


def test_delete_unknown_id_does_not_raise(db_connection):
    repository = SQLiteConversationRepository(db_connection)
    repository.delete("unbekannt")  # kein Fehler erwartet


# ── Persistenzverantwortung ────────────────────────────────────────────────

def test_save_conversation_does_not_persist_participants(db_connection):
    """ConversationRepository.save() darf die participants-Tabelle nicht beschreiben.
    Persistenz von Participants obliegt ausschließlich dem ParticipantRepository.
    """
    from conclave.infrastructure.sqlite.participant_repository import SQLiteParticipantRepository
    from conclave.domain.participant import Participant, ParticipantType

    conv_repo = SQLiteConversationRepository(db_connection)
    part_repo = SQLiteParticipantRepository(db_connection)

    conversation = Conversation.create()
    participant = Participant(
        id="p-test-1",
        conversation_id=conversation.id,
        participant_type=ParticipantType.MODEL,
        name="Claude",
    )
    conversation.add_participant(participant)

    conv_repo.save(conversation)

    # Participants dürfen NICHT automatisch in der DB gelandet sein
    rows = part_repo.list_by_conversation_id(conversation.id)
    assert rows == [], (
        "ConversationRepository.save() hat Participants selbstständig persistiert – "
        "Persistenzverantwortung liegt beim ParticipantRepository."
    )
