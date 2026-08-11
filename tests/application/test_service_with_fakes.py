# tests/application/test_service_with_fakes.py

from conclave.application.conversation_flow import ConversationFlowService
from conclave.application.ports import (
    ConversationRepository,
    MessageRepository,
    ParticipantRepository,
)
from conclave.domain.conversation import Conversation
from conclave.domain.message import Message
from conclave.domain.participant import Participant, ParticipantType


class FakeConversationRepository:
    def __init__(self):
        self._store: dict[str, Conversation] = {}

    def save(self, conversation: Conversation) -> None:
        self._store[conversation.id] = conversation

    def load(self, conversation_id: str) -> Conversation | None:
        return self._store.get(conversation_id)

    def list_all(self) -> list[Conversation]:
        return list(self._store.values())

    def delete(self, conversation_id: str) -> None:
        self._store.pop(conversation_id, None)

class FakeMessageRepository:
    def __init__(self):
        self._store: list[Message] = []

    def save(self, message: Message) -> None:
        self._store.append(message)

    def list_by_conversation_id(self, conversation_id: str) -> list[Message]:
        return [m for m in self._store if m.conversation_id == conversation_id]


class FakeParticipantRepository:
    def __init__(self):
        self._store: list[Participant] = []

    def save(self, participant: Participant) -> None:
        self._store.append(participant)

    def list_by_conversation_id(self, conversation_id: str) -> list[Participant]:
        return [p for p in self._store if p.conversation_id == conversation_id]

    def delete_by_conversation(self, conversation_id: str) -> None:
        self._store = [p for p in self._store if p.conversation_id != conversation_id]

    def delete(self, conversation_id: str, participant_id: str) -> None:
        self._store = [
            p for p in self._store
            if not (p.conversation_id == conversation_id and p.id == participant_id)
        ]


def make_service():
    return ConversationFlowService(
        conversation_repository=FakeConversationRepository(),
        message_repository=FakeMessageRepository(),
        participant_repository=FakeParticipantRepository(),
    )


def test_service_works_with_fake_repositories():
    service = make_service()
    conversation = service.create_conversation()
    assert conversation.id is not None


def test_service_add_user_message_with_fake_repositories():
    service = make_service()
    conversation = service.create_conversation()
    updated = service.add_user_message(conversation.id, "Hallo")
    assert len(updated.messages) == 1
    assert updated.messages[0].content == "Hallo"


def test_service_register_participant_with_fake_repositories():
    service = make_service()
    conversation = service.create_conversation()
    updated = service.register_participant(
        conversation_id=conversation.id,
        participant_id="p1",
        participant_type=ParticipantType.MODEL,
        name="Model A",
    )
    assert len(updated.participants) == 1
    assert updated.participants[0].id == "p1"


def test_fake_repositories_satisfy_protocols():
    assert isinstance(FakeConversationRepository(), ConversationRepository)
    assert isinstance(FakeMessageRepository(), MessageRepository)
    assert isinstance(FakeParticipantRepository(), ParticipantRepository)
