import uuid
from datetime import datetime

from conclave.domain.conversation import Conversation
from conclave.domain.participant import Participant, ParticipantType
from conclave.infrastructure.sqlite.conversation_repository import SQLiteConversationRepository
from conclave.infrastructure.sqlite.participant_repository import SQLiteParticipantRepository


def test_save_and_reload_conversation_with_one_participant(db_connection):
    conv_repo = SQLiteConversationRepository(db_connection)
    part_repo = SQLiteParticipantRepository(db_connection)

    conversation = Conversation(id=str(uuid.uuid4()))
    participant = Participant(
        id=str(uuid.uuid4()),
        conversation_id=conversation.id,
        participant_type=ParticipantType.USER,
        name="Alice",
    )
    conversation.add_participant(participant)

    conv_repo.save(conversation)
    part_repo.save(participant)
    db_connection.commit()

    reloaded = conv_repo.get_by_id(conversation.id)

    assert reloaded is not None
    assert reloaded.id == conversation.id
    assert len(reloaded.participants) == 1
    assert reloaded.participants[0].id == participant.id
    assert reloaded.participants[0].conversation_id == conversation.id
    assert reloaded.participants[0].participant_type == ParticipantType.USER
    assert reloaded.participants[0].name == "Alice"


def test_save_and_reload_conversation_with_multiple_participants(db_connection):
    conv_repo = SQLiteConversationRepository(db_connection)
    part_repo = SQLiteParticipantRepository(db_connection)

    conversation = Conversation(id=str(uuid.uuid4()))
    participant_1 = Participant(
        id=str(uuid.uuid4()),
        conversation_id=conversation.id,
        participant_type=ParticipantType.USER,
        name="Alice",
    )
    participant_2 = Participant(
        id=str(uuid.uuid4()),
        conversation_id=conversation.id,
        participant_type=ParticipantType.MODEL,
        name="GPT-Adapter",
    )

    conversation.add_participant(participant_1)
    conversation.add_participant(participant_2)

    conv_repo.save(conversation)
    part_repo.save(participant_1)
    part_repo.save(participant_2)
    db_connection.commit()

    reloaded = conv_repo.get_by_id(conversation.id)

    assert reloaded is not None
    assert reloaded.id == conversation.id
    assert len(reloaded.participants) == 2

    participant_ids = {p.id for p in reloaded.participants}
    participant_names = {p.name for p in reloaded.participants}
    participant_types = {p.participant_type for p in reloaded.participants}

    assert participant_1.id in participant_ids
    assert participant_2.id in participant_ids
    assert "Alice" in participant_names
    assert "GPT-Adapter" in participant_names
    assert ParticipantType.USER in participant_types
    assert ParticipantType.MODEL in participant_types


def test_reload_restores_participant_type_as_enum(db_connection):
    conv_repo = SQLiteConversationRepository(db_connection)
    part_repo = SQLiteParticipantRepository(db_connection)

    conversation = Conversation(id=str(uuid.uuid4()))
    participant = Participant(
        id=str(uuid.uuid4()),
        conversation_id=conversation.id,
        participant_type=ParticipantType.MODEL,
        name="GPT-Adapter",
    )
    conversation.add_participant(participant)

    conv_repo.save(conversation)
    part_repo.save(participant)
    db_connection.commit()

    reloaded = conv_repo.get_by_id(conversation.id)

    assert reloaded is not None
    assert len(reloaded.participants) == 1
    assert reloaded.participants[0].participant_type == ParticipantType.MODEL
    assert isinstance(reloaded.participants[0].participant_type, ParticipantType)


def test_reload_returns_participants_for_the_requested_conversation_only(db_connection):
    conv_repo = SQLiteConversationRepository(db_connection)
    part_repo = SQLiteParticipantRepository(db_connection)

    conversation_1 = Conversation(id=str(uuid.uuid4()))
    conversation_2 = Conversation(id=str(uuid.uuid4()))

    participant_1 = Participant(
        id=str(uuid.uuid4()),
        conversation_id=conversation_1.id,
        participant_type=ParticipantType.USER,
        name="Alice",
    )
    participant_2 = Participant(
        id=str(uuid.uuid4()),
        conversation_id=conversation_2.id,
        participant_type=ParticipantType.MODEL,
        name="GPT-Adapter",
    )

    conversation_1.add_participant(participant_1)
    conversation_2.add_participant(participant_2)

    conv_repo.save(conversation_1)
    conv_repo.save(conversation_2)
    part_repo.save(participant_1)
    part_repo.save(participant_2)
    db_connection.commit()

    reloaded_1 = conv_repo.get_by_id(conversation_1.id)
    reloaded_2 = conv_repo.get_by_id(conversation_2.id)

    assert reloaded_1 is not None
    assert reloaded_2 is not None

    assert len(reloaded_1.participants) == 1
    assert reloaded_1.participants[0].id == participant_1.id
    assert reloaded_1.participants[0].name == "Alice"

    assert len(reloaded_2.participants) == 1
    assert reloaded_2.participants[0].id == participant_2.id
    assert reloaded_2.participants[0].name == "GPT-Adapter"


def test_get_by_id_returns_none_for_unknown_conversation(db_connection):
    repository = SQLiteConversationRepository(db_connection)

    unknown_conversation_id = str(uuid.uuid4())

    result = repository.get_by_id(unknown_conversation_id)

    assert result is None


def test_list_by_conversation_id_returns_created_at_as_datetime(db_connection):
    conversation = Conversation(id=str(uuid.uuid4()))
    conversation_repository = SQLiteConversationRepository(db_connection)
    conversation_repository.save(conversation)

    participant = Participant(
        id=str(uuid.uuid4()),
        conversation_id=conversation.id,
        participant_type=ParticipantType.MODEL,
        name="Model A",
    )
    participant_repository = SQLiteParticipantRepository(db_connection)
    participant_repository.save(participant)

    results = participant_repository.list_by_conversation_id(conversation.id)

    assert len(results) == 1
    assert isinstance(results[0].created_at, datetime)


# ── delete_by_conversation ─────────────────────────────────────────────────

def test_delete_by_conversation_removes_all_its_participants(db_connection):
    """ParticipantRepository.delete_by_conversation() entfernt alle Participants
    einer Conversation, ohne andere Conversations zu berühren.
    """
    from conclave.infrastructure.sqlite.conversation_repository import SQLiteConversationRepository

    conv_repo = SQLiteConversationRepository(db_connection)
    part_repo = SQLiteParticipantRepository(db_connection)

    conv_a = Conversation(id=str(uuid.uuid4()))
    conv_b = Conversation(id=str(uuid.uuid4()))
    conv_repo.save(conv_a)
    conv_repo.save(conv_b)

    p1 = Participant(id="p1", conversation_id=conv_a.id,
                     participant_type=ParticipantType.MODEL, name="Alpha")
    p2 = Participant(id="p2", conversation_id=conv_a.id,
                     participant_type=ParticipantType.MODEL, name="Beta")
    p3 = Participant(id="p3", conversation_id=conv_b.id,
                     participant_type=ParticipantType.MODEL, name="Gamma")

    part_repo.save(p1)
    part_repo.save(p2)
    part_repo.save(p3)
    db_connection.commit()

    part_repo.delete_by_conversation(conv_a.id)
    db_connection.commit()

    assert part_repo.list_by_conversation_id(conv_a.id) == []
    remaining = part_repo.list_by_conversation_id(conv_b.id)
    assert len(remaining) == 1
    assert remaining[0].id == "p3"
