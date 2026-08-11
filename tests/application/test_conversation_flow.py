# tests/application/test_conversation_flow.py

import pytest

from conclave.domain.conversation import Conversation
from conclave.domain.errors import ConversationNotFound
from conclave.domain.message import MessageAuthorType
from conclave.domain.participant import ParticipantType


def test_create_conversation_returns_initial_persisted_conversation(service):
    created = service.create_conversation()
    loaded = service.load_conversation(created.id)

    assert created.id == loaded.id
    assert created.status == loaded.status
    assert created.messages == []
    assert created.participants == []
    assert loaded.messages == []
    assert loaded.participants == []


def test_add_user_message_returns_updated_conversation_and_persists_complete_state(service):
    conversation = service.create_conversation()

    updated = service.add_user_message(conversation.id, "Hello Conclave")
    loaded = service.load_conversation(conversation.id)

    assert isinstance(updated, Conversation)
    assert updated.id == conversation.id
    assert updated.status == "active"
    assert len(updated.messages) == 1

    returned_message = updated.messages[0]
    assert returned_message.conversation_id == conversation.id
    assert returned_message.author_type == MessageAuthorType.USER
    assert returned_message.content == "Hello Conclave"
    assert returned_message.sequence == 1
    assert returned_message.created_at is not None

    assert loaded is not None
    assert loaded.id == conversation.id
    assert loaded.status == "active"
    assert len(loaded.messages) == 1

    persisted_message = loaded.messages[0]
    assert persisted_message.conversation_id == conversation.id
    assert persisted_message.author_type == MessageAuthorType.USER
    assert persisted_message.content == "Hello Conclave"
    assert persisted_message.sequence == 1
    assert persisted_message.created_at is not None


def test_add_model_message_returns_updated_conversation_and_persists_message(service):
    conversation = service.create_conversation()

    conversation = service.register_participant(
        conversation_id=conversation.id,
        participant_id="assistant-1",
        participant_type=ParticipantType.MODEL,
        name="Model A",
    )

    reloaded = service.load_conversation(conversation.id)
    assert len(conversation.participants) == 1
    assert conversation.participants[0].id == "assistant-1"
    assert len(reloaded.participants) == 1
    assert reloaded.participants[0].id == "assistant-1"

    updated = service.add_model_message(
        conversation_id=conversation.id,
        participant_id="assistant-1",
        content="Antwort des Modells",
    )
    loaded = service.load_conversation(conversation.id)

    assert updated.id == conversation.id
    assert updated.status == "active"
    assert len(updated.messages) == 1

    returned_message = updated.messages[0]
    assert returned_message.conversation_id == conversation.id
    assert returned_message.content == "Antwort des Modells"
    assert returned_message.sequence == 1
    assert returned_message.created_at is not None
    assert returned_message.author_id == "assistant-1"
    assert returned_message.author_type == MessageAuthorType.MODEL

    assert loaded.id == conversation.id
    assert loaded.status == "active"
    assert len(loaded.messages) == 1

    persisted_message = loaded.messages[0]
    assert persisted_message.conversation_id == conversation.id
    assert persisted_message.content == "Antwort des Modells"
    assert persisted_message.sequence == 1
    assert persisted_message.created_at is not None
    assert persisted_message.author_id == "assistant-1"
    assert persisted_message.author_type == MessageAuthorType.MODEL


def test_cannot_add_message_to_unknown_conversation(service):
    unknown_conversation_id = "11111111-1111-1111-1111-111111111111"

    with pytest.raises(ConversationNotFound):
        service.add_user_message(unknown_conversation_id, "Hello Conclave")


def test_model_message_author_type_is_message_author_type_enum(service):
    conversation = service.create_conversation()
    service.register_participant(
        conversation_id=conversation.id,
        participant_id="assistant-1",
        participant_type=ParticipantType.MODEL,
        name="Model A",
    )
    updated = service.add_model_message(
        conversation_id=conversation.id,
        participant_id="assistant-1",
        content="Antwort",
    )

    message = updated.messages[0]
    assert isinstance(message.author_type, MessageAuthorType)
    assert message.author_type == MessageAuthorType.MODEL


def test_list_conversations_returns_all(service):
    service.create_conversation()
    service.create_conversation()
    service.create_conversation()

    result = service.list_conversations()

    assert len(result) == 3


def test_list_conversations_returns_empty_initially(service):
    result = service.list_conversations()
    assert result == []


def test_delete_conversation_removes_it(service):
    from conclave.domain.errors import ConversationNotFound

    conversation = service.create_conversation()
    service.delete_conversation(conversation.id)

    with pytest.raises(ConversationNotFound):
        service.load_conversation(conversation.id)


def test_delete_unknown_conversation_raises(service):
    from conclave.domain.errors import ConversationNotFound

    with pytest.raises(ConversationNotFound):
        service.delete_conversation("unbekannt")
