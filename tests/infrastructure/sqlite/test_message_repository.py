# tests/infrastructure/sqlite/test_message_repository.py

from conclave.domain.conversation import Conversation
from conclave.infrastructure.sqlite.conversation_repository import (
    SQLiteConversationRepository,
)
from conclave.infrastructure.sqlite.message_repository import SQLiteMessageRepository


def test_message_repository_saves_and_loads_messages_for_conversation(db_connection):
    conversation_repository = SQLiteConversationRepository(db_connection)
    message_repository = SQLiteMessageRepository(db_connection)

    conversation = Conversation.create()
    conversation_repository.save(conversation)

    message = conversation.add_user_message("Hello Conclave")
    message_repository.save(message)

    loaded_messages = message_repository.list_by_conversation_id(conversation.id)

    assert len(loaded_messages) == 1
    assert loaded_messages[0].id == message.id
    assert loaded_messages[0].conversation_id == conversation.id
    assert loaded_messages[0].author_type == message.author_type
    assert loaded_messages[0].content == "Hello Conclave"
    assert loaded_messages[0].sequence == 1
    assert loaded_messages[0].created_at == message.created_at


def test_messages_are_returned_in_sequence_order(db_connection):
    """Sequence wird atomar von der DB vergeben — Reihenfolge der saves bestimmt die Sequence."""
    conversation_repository = SQLiteConversationRepository(db_connection)
    message_repository = SQLiteMessageRepository(db_connection)

    conversation = Conversation.create()
    conversation_repository.save(conversation)

    first = conversation.add_user_message("First")
    second = conversation.add_user_message("Second")
    third = conversation.add_user_message("Third")

    message_repository.save(first)
    message_repository.save(second)
    message_repository.save(third)

    loaded_messages = message_repository.list_by_conversation_id(conversation.id)

    assert [message.sequence for message in loaded_messages] == [1, 2, 3]
    assert [message.content for message in loaded_messages] == [
        "First",
        "Second",
        "Third",
    ]