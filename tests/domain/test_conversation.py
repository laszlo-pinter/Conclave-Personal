# tests/domain/test_conversation.py

from conclave.domain.conversation import Conversation
from conclave.domain.message import MessageAuthorType


def test_create_conversation_creates_empty_conversation():
    conversation = Conversation.create()

    assert conversation.id is not None
    assert str(conversation.id) != ""
    assert conversation.status == "active"
    assert conversation.created_at is not None
    assert conversation.messages == []


def test_add_user_message_appends_message_to_conversation():
    conversation = Conversation.create()

    message = conversation.add_user_message("Hello Conclave")

    assert len(conversation.messages) == 1
    assert message in conversation.messages
    assert message.conversation_id == conversation.id
    assert message.author_type == MessageAuthorType.USER
    assert message.content == "Hello Conclave"


def test_first_user_message_gets_sequence_1():
    conversation = Conversation.create()

    message = conversation.add_user_message("Hello Conclave")

    assert message.sequence == 1