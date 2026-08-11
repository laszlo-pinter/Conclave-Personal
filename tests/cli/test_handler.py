# tests/cli/test_handler.py

import pytest
from unittest.mock import patch

from conclave.cli.handler import CLIHandler, CLIResult
from conclave.domain.participant import ParticipantType


# ── Conversation erstellen ─────────────────────────────────────────────────

def test_new_conversation_returns_success_with_id(service):
    handler = CLIHandler(service)
    result = handler.new_conversation()

    assert result.success
    assert result.data["conversation_id"] is not None
    assert result.message is not None


def test_new_conversation_persists(service):
    handler = CLIHandler(service)
    result = handler.new_conversation()

    conversation_id = result.data["conversation_id"]
    loaded = service.load_conversation(conversation_id)
    assert loaded.id == conversation_id


# ── Conversation anzeigen ──────────────────────────────────────────────────

def test_show_conversation_returns_id_status_counts(service):
    handler = CLIHandler(service)
    conv_id = handler.new_conversation().data["conversation_id"]
    service.add_user_message(conv_id, "Hallo")

    result = handler.show_conversation(conv_id)

    assert result.success
    assert result.data["id"] == conv_id
    assert result.data["status"] == "active"
    assert result.data["message_count"] == 1
    assert result.data["participant_count"] == 0


def test_show_conversation_unknown_id_returns_failure(service):
    handler = CLIHandler(service)
    result = handler.show_conversation("unbekannt")

    assert not result.success
    assert "unbekannt" in result.message


# ── Participant registrieren ───────────────────────────────────────────────

def test_add_participant_returns_success(service):
    handler = CLIHandler(service)
    conv_id = handler.new_conversation().data["conversation_id"]

    result = handler.add_participant(
        conversation_id=conv_id,
        participant_id="p1",
        name="Claude",
        participant_type=ParticipantType.MODEL,
    )

    assert result.success
    assert result.data["participant_id"] == "p1"


def test_add_participant_unknown_conversation_returns_failure(service):
    handler = CLIHandler(service)
    result = handler.add_participant(
        conversation_id="unbekannt",
        participant_id="p1",
        name="Claude",
        participant_type=ParticipantType.MODEL,
    )

    assert not result.success


def test_add_duplicate_participant_returns_failure(service):
    handler = CLIHandler(service)
    conv_id = handler.new_conversation().data["conversation_id"]
    handler.add_participant(conv_id, "p1", "Claude", ParticipantType.MODEL)

    result = handler.add_participant(conv_id, "p1", "Claude Kopie", ParticipantType.MODEL)

    assert not result.success


# ── User-Message hinzufügen ────────────────────────────────────────────────

def test_add_message_returns_success_with_sequence(service):
    handler = CLIHandler(service)
    conv_id = handler.new_conversation().data["conversation_id"]

    result = handler.add_message(conv_id, "Hallo Welt")

    assert result.success
    assert result.data["sequence"] == 1


def test_add_message_unknown_conversation_returns_failure(service):
    handler = CLIHandler(service)
    result = handler.add_message("unbekannt", "Hallo")

    assert not result.success


# ── Participant aufrufen ───────────────────────────────────────────────────

def test_invoke_participant_returns_model_response(service):
    from conclave.application.adapter_registry import AdapterRegistry
    from conclave.domain.conversation import Conversation
    from conclave.domain.participant import Participant

    class FakeAdapter:
        provider = "test"
        def complete(self, conversation: Conversation, participant: Participant) -> str:
            return "Antwort vom Modell"

    registry = AdapterRegistry()
    registry.register("p1", FakeAdapter())
    service.set_adapter_registry(registry)

    handler = CLIHandler(service)
    conv_id = handler.new_conversation().data["conversation_id"]
    handler.add_participant(conv_id, "p1", "Claude", ParticipantType.MODEL)
    handler.add_message(conv_id, "Frage")

    result = handler.invoke_participant(conv_id, "p1")

    assert result.success
    assert result.data["content"] == "Antwort vom Modell"
    assert result.data["participant_id"] == "p1"


def test_invoke_participant_no_adapter_returns_failure(service):
    handler = CLIHandler(service)
    conv_id = handler.new_conversation().data["conversation_id"]
    handler.add_participant(conv_id, "p1", "Claude", ParticipantType.MODEL)
    handler.add_message(conv_id, "Frage")

    result = handler.invoke_participant(conv_id, "p1")

    assert not result.success
    assert "p1" in result.message


# ── list ──────────────────────────────────────────────────────────────────

def test_list_conversations_returns_all(service):
    handler = CLIHandler(service)
    service.create_conversation()
    service.create_conversation()

    result = handler.list_conversations()

    assert result.success
    assert len(result.data["conversations"]) == 2


def test_list_conversations_empty_returns_success(service):
    handler = CLIHandler(service)
    result = handler.list_conversations()

    assert result.success
    assert result.data["conversations"] == []


# ── delete ────────────────────────────────────────────────────────────────

def test_delete_conversation_returns_success(service):
    handler = CLIHandler(service)
    conv_id = handler.new_conversation().data["conversation_id"]

    result = handler.delete_conversation(conv_id)

    assert result.success
    assert result.data["conversation_id"] == conv_id


def test_delete_conversation_unknown_returns_failure(service):
    handler = CLIHandler(service)
    result = handler.delete_conversation("unbekannt")

    assert not result.success
    assert "unbekannt" in result.message


def test_delete_conversation_removes_it_from_list(service):
    handler = CLIHandler(service)
    conv_id = handler.new_conversation().data["conversation_id"]
    handler.delete_conversation(conv_id)

    result = handler.list_conversations()
    ids = [c["id"] for c in result.data["conversations"]]
    assert conv_id not in ids


def test_set_agent_key_updates_api_key(service, agent_service):
    handler = CLIHandler(service, agent_service=agent_service)
    from conclave.domain.agent import Agent
    agent_service.create_agent(
        Agent(id="a1", name="Claude", provider="anthropic",
              model="claude-sonnet-4-20250514", api_key="alt-key")
    )

    result = handler.set_agent_key("a1", "neuer-key")

    assert result.success
    updated = agent_service.get_agent("a1")
    assert updated.api_key == "neuer-key"


def test_set_agent_key_unknown_agent(service, agent_service):
    handler = CLIHandler(service, agent_service=agent_service)

    result = handler.set_agent_key("unbekannt", "sk-test")

    assert not result.success


def test_agent_test_returns_structured_success(service, agent_service):
    from conclave.domain.agent import Agent

    class FakeAdapter:
        def complete(self, conversation, participant):
            return "OK"

    handler = CLIHandler(service, agent_service=agent_service)
    agent_service.create_agent(
        Agent(id="a1", name="Test", provider="custom", model="m", api_url="https://example.test")
    )

    with patch("conclave.cli.bootstrap._make_adapter", return_value=FakeAdapter()):
        result = handler.test_agent("a1")

    assert result["success"] is True
    assert result["status"] == "ok"
    assert result["provider"] == "custom"
    assert result["model"] == "m"
    assert isinstance(result["latency_ms"], int)


def test_agent_test_uses_provider_fallback_key(service, agent_service):
    from conclave.domain.agent import Agent

    class FakeAdapter:
        def complete(self, conversation, participant):
            return "OK"

    handler = CLIHandler(
        service,
        agent_service=agent_service,
        provider_fallback_keys={"openai-responses": "sk-fallback"},
    )
    agent_service.create_agent(
        Agent(id="a1", name="Test", provider="openai-responses", model="gpt-5.6")
    )

    with patch("conclave.cli.bootstrap._make_adapter", return_value=FakeAdapter()) as make_adapter:
        result = handler.test_agent("a1")

    assert result["success"] is True
    assert make_adapter.call_args.kwargs["api_key"] == "sk-fallback"


def test_agent_test_returns_not_configured_details(service, agent_service):
    from conclave.domain.agent import Agent

    handler = CLIHandler(service, agent_service=agent_service)
    agent_service.create_agent(Agent(id="a1", name="Test", provider="custom", model="m"))

    with patch("conclave.cli.bootstrap._make_adapter", return_value=None):
        result = handler.test_agent("a1")

    assert result["success"] is False
    assert result["status"] == "not_configured"
    assert "hint" in result


def test_workspace_write_read_and_list(service, tmp_path, monkeypatch):
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(tmp_path))
    handler = CLIHandler(service)

    written = handler.workspace_write("notes/a.txt", "Hallo")
    read = handler.workspace_read("notes/a.txt")
    listed = handler.workspace_list()

    assert written.success
    assert read.data["content"] == "Hallo"
    assert listed.data["files"][0]["path"] == "notes/a.txt"


def test_workspace_blocks_path_escape(service, tmp_path, monkeypatch):
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(tmp_path))
    handler = CLIHandler(service)

    result = handler.workspace_write("../outside.txt", "nope")

    assert not result.success


def test_workspace_cli_hides_hidden_files(service, tmp_path, monkeypatch):
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(tmp_path))
    (tmp_path / ".private").mkdir()
    (tmp_path / ".private" / "secret.txt").write_text("SECRET", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("Hallo", encoding="utf-8")
    handler = CLIHandler(service)

    listed = handler.workspace_list()
    read = handler.workspace_read(".private/secret.txt")
    write = handler.workspace_write(".private/new.txt", "nope")

    paths = {item["path"] for item in listed.data["files"]}
    assert "notes.txt" in paths
    assert ".private/secret.txt" not in paths
    assert not read.success
    assert not write.success


def test_workspace_cli_blocks_large_read_and_write(service, tmp_path, monkeypatch):
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("CONCLAVE_WORKSPACE_UI_READ_LIMIT_BYTES", "8")
    monkeypatch.setenv("CONCLAVE_WORKSPACE_WRITE_LIMIT_BYTES", "8")
    (tmp_path / "large.txt").write_text("zu viel text", encoding="utf-8")
    handler = CLIHandler(service)

    read = handler.workspace_read("large.txt")
    write = handler.workspace_write("new.txt", "zu viel text")

    assert not read.success
    assert "gross" in read.message
    assert not write.success
    assert "gross" in write.message


def test_create_backup_returns_zip(service, tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("Hallo", encoding="utf-8")
    db_path = tmp_path / "conclave.db"
    db_path.write_text("db", encoding="utf-8")
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(workspace))
    handler = CLIHandler(service)

    result = handler.create_backup(db_path=db_path, backup_dir=tmp_path / "backups")

    assert result.success
    assert result.data["backup_path"].endswith(".zip")
