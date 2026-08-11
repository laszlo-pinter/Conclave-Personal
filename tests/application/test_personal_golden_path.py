from types import SimpleNamespace

from conclave.application.adapter_registry import AdapterRegistry
from conclave.application.conversation_flow import ConversationFlowService
from conclave.domain.agent import Agent
from conclave.domain.participant import ParticipantType
from conclave.infrastructure.sqlite.conversation_repository import SQLiteConversationRepository
from conclave.infrastructure.sqlite.message_repository import SQLiteMessageRepository
from conclave.infrastructure.sqlite.participant_repository import SQLiteParticipantRepository
from conclave.infrastructure.sqlite.run_repository import SQLiteRunRepository


class FakeProviderAdapter:
    provider = "fake"
    _model = "fake-reviewer"

    def __init__(self):
        self.last_usage = SimpleNamespace(input_tokens=11, output_tokens=7)
        self.seen_prompt = ""

    def complete(self, conversation, participant):
        self.seen_prompt = "\n".join(message.content for message in conversation.messages)
        assert "Workspace-Fakt" in self.seen_prompt
        assert participant.id == "writer"
        return "@save(report.md)\n# Ergebnis\nWorkspace-Fakt verarbeitet.\n@endsave"


def _new_service(db_connection):
    return ConversationFlowService(
        conversation_repository=SQLiteConversationRepository(db_connection),
        message_repository=SQLiteMessageRepository(db_connection),
        participant_repository=SQLiteParticipantRepository(db_connection),
    )


def test_personal_golden_path_with_fake_provider_persists_core_flow(
    agent_service,
    db_connection,
    tmp_path,
    monkeypatch,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "briefing.md").write_text("Workspace-Fakt", encoding="utf-8")
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(workspace))

    agent = agent_service.create_agent(
        Agent(
            id="writer",
            name="Writer",
            provider="fake",
            model="fake-reviewer",
            role="Writer",
            preset="custom",
        )
    )
    assert agent_service.get_agent(agent.id).name == "Writer"

    service = _new_service(db_connection)
    run_repo = SQLiteRunRepository(db_connection)
    service.set_run_repository(run_repo)

    conversation = service.create_conversation(topic="Golden Path")
    service.register_participant(conversation.id, agent.id, ParticipantType.MODEL, agent.name)
    service.add_user_message(conversation.id, "Bitte nutze @workspace/briefing.md.")

    adapter = FakeProviderAdapter()
    registry = AdapterRegistry()
    registry.register(agent.id, adapter)
    service.set_adapter_registry(registry)

    service.invoke_participant(conversation.id, agent.id)

    output = workspace / "output" / "report.md"
    assert output.read_text(encoding="utf-8") == "# Ergebnis\nWorkspace-Fakt verarbeitet."

    runs = run_repo.list_by_conversation(conversation.id)
    assert len(runs) == 1
    assert runs[0].kind == "invoke"
    assert runs[0].status == "succeeded"
    assert runs[0].participants == ["writer"]
    assert runs[0].usage is not None
    assert runs[0].usage.total_tokens == 18

    restarted_service = _new_service(db_connection)
    loaded = restarted_service.load_conversation(conversation.id)

    assert loaded.topic == "Golden Path"
    assert [participant.id for participant in loaded.participants] == ["writer"]
    assert any("Bitte nutze @workspace/briefing.md." in message.content for message in loaded.messages)
    assert any("@workspace/output/report.md" in message.content for message in loaded.messages)
