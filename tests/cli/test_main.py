# tests/cli/test_main.py

import json
from unittest.mock import MagicMock, patch

import pytest

from conclave.cli.handler import CLIResult
from conclave.cli.main import run


def make_handler_mock(**overrides):
    """Baut einen CLIHandler-Mock mit sinnvollen Defaults."""
    handler = MagicMock()
    handler.new_conversation.return_value = CLIResult(
        success=True,
        message="Conversation erstellt: conv-1",
        data={"conversation_id": "conv-1"},
    )
    handler.show_conversation.return_value = CLIResult(
        success=True,
        message="Conversation conv-1",
        data={
            "id": "conv-1",
            "status": "active",
            "message_count": 0,
            "participant_count": 0,
            "messages": [],
            "participants": [],
        },
    )
    handler.add_participant.return_value = CLIResult(
        success=True,
        message="Participant registriert.",
        data={"participant_id": "p1"},
    )
    handler.add_message.return_value = CLIResult(
        success=True,
        message="Message hinzugefügt.",
        data={"sequence": 1, "content": "Hallo"},
    )
    handler.invoke_participant.return_value = CLIResult(
        success=True,
        message="Antwort erhalten.",
        data={"participant_id": "p1", "content": "Modellantwort", "sequence": 2},
    )
    for attr, value in overrides.items():
        setattr(handler, attr, value)
    return handler


def patch_run(handler):
    return patch.multiple(
        "conclave.cli.main",
        build_service=MagicMock(return_value=MagicMock()),
        build_agent_service=MagicMock(return_value=MagicMock()),
        build_registry=MagicMock(return_value=None),
        CLIHandler=MagicMock(return_value=handler),
    )


def test_new_command_returns_zero_exit_code():
    handler = make_handler_mock()
    with patch_run(handler):
        code = run(["new"])
    assert code == 0


def test_new_command_calls_new_conversation():
    handler = make_handler_mock()
    with patch_run(handler):
        run(["new"])
    handler.new_conversation.assert_called_once()


def test_show_command_passes_conversation_id():
    handler = make_handler_mock()
    with patch_run(handler):
        run(["show", "conv-abc"])
    handler.show_conversation.assert_called_once_with("conv-abc")


def test_add_participant_passes_all_args():
    handler = make_handler_mock()
    with patch_run(handler):
        run(["add-participant", "conv-1", "p1", "--name", "Claude", "--type", "model"])
    handler.add_participant.assert_called_once()
    call_kwargs = handler.add_participant.call_args.kwargs
    assert call_kwargs["conversation_id"] == "conv-1"
    assert call_kwargs["participant_id"] == "p1"
    assert call_kwargs["name"] == "Claude"


def test_message_command_passes_content():
    handler = make_handler_mock()
    with patch_run(handler):
        run(["message", "conv-1", "Hallo Welt"])
    handler.add_message.assert_called_once_with("conv-1", "Hallo Welt")


def test_invoke_command_passes_ids():
    handler = make_handler_mock()
    with patch_run(handler):
        run(["invoke", "conv-1", "p1"])
    handler.invoke_participant.assert_called_once_with("conv-1", "p1")


def test_failed_result_returns_nonzero_exit_code():
    handler = make_handler_mock()
    handler.show_conversation.return_value = CLIResult(
        success=False,
        message="Nicht gefunden.",
    )
    with patch_run(handler):
        code = run(["show", "unbekannt"])
    assert code == 1


def test_json_flag_produces_valid_json(capsys):
    handler = make_handler_mock()
    with patch_run(handler):
        run(["--json", "new"])
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["success"] is True
    assert "conversation_id" in parsed


def test_orchestrate_command_passes_participants(capsys):
    handler = make_handler_mock()
    handler.orchestrate.return_value = CLIResult(
        success=True,
        message="2 Antwort(en) erhalten.",
        data={"responses": []},
    )
    with patch_run(handler):
        code = run(["orchestrate", "conv-1", "p1", "p2"])
    assert code == 0
    handler.orchestrate.assert_called_once_with("conv-1", ["p1", "p2"])


def test_list_command_calls_list_conversations():
    handler = make_handler_mock()
    handler.list_conversations.return_value = CLIResult(
        success=True,
        message="0 Conversations gefunden.",
        data={"conversations": []},
    )
    with patch_run(handler):
        code = run(["list"])
    assert code == 0
    handler.list_conversations.assert_called_once()


def test_delete_command_passes_conversation_id():
    handler = make_handler_mock()
    handler.delete_conversation.return_value = CLIResult(
        success=True,
        message="Gelöscht.",
        data={"conversation_id": "conv-abc"},
    )
    with patch_run(handler):
        run(["delete", "conv-abc"])
    handler.delete_conversation.assert_called_once_with("conv-abc")


# ── Agenten-Befehle ───────────────────────────────────────────────────────

def test_agents_command_calls_list_agents():
    handler = make_handler_mock()
    handler.list_agents.return_value = CLIResult(
        success=True, message="1 Agent.", data={"agents": []}
    )
    with patch_run(handler):
        code = run(["agents"])
    assert code == 0
    handler.list_agents.assert_called_once()


def test_agent_new_command_calls_create_agent():
    handler = make_handler_mock()
    handler.create_agent.return_value = CLIResult(
        success=True, message="Erstellt.", data={"id": "a1"}
    )
    with patch_run(handler):
        code = run(["agent-new", "a1", "--name", "Claude", "--model", "claude-sonnet-4-20250514"])
    assert code == 0
    handler.create_agent.assert_called_once()


def test_agent_new_accepts_custom_provider_and_preset():
    handler = make_handler_mock()
    handler.create_agent.return_value = CLIResult(
        success=True, message="Erstellt.", data={"id": "a1"}
    )
    with patch_run(handler):
        code = run([
            "agent-new", "a1", "--name", "DeepSeek", "--provider", "deepseek",
            "--model", "deepseek-chat", "--preset", "deepseek",
        ])
    assert code == 0
    agent = handler.create_agent.call_args.args[0]
    assert agent.provider == "deepseek"
    assert agent.preset == "deepseek"


def test_agent_edit_command_calls_update_agent():
    handler = make_handler_mock()
    handler.get_agent.return_value = CLIResult(
        success=True, message="ok",
        data={"id": "a1", "name": "Alt", "provider": "anthropic",
              "model": "m", "role": "", "topic": "", "system_prompt": "",
              "created_at": "2026-01-01T00:00:00+00:00"}
    )
    handler.update_agent.return_value = CLIResult(
        success=True, message="Aktualisiert.", data={"id": "a1"}
    )
    with patch_run(handler):
        code = run(["agent-edit", "a1", "--name", "Neu", "--model", "m"])
    assert code == 0
    handler.update_agent.assert_called_once()


def test_agent_delete_command_calls_delete_agent():
    handler = make_handler_mock()
    handler.delete_agent.return_value = CLIResult(
        success=True, message="Gelöscht.", data={"id": "a1"}
    )
    with patch_run(handler):
        code = run(["agent-delete", "a1"])
    assert code == 0
    handler.delete_agent.assert_called_once_with("a1")


def test_agent_test_command_calls_test_agent():
    handler = make_handler_mock()
    handler.test_agent.return_value = {"success": True, "message": "Antwort: OK"}
    with patch_run(handler):
        code = run(["agent-test", "a1"])
    assert code == 0
    handler.test_agent.assert_called_once_with("a1")


def test_usage_command_calls_token_usage():
    handler = make_handler_mock()
    handler.token_usage.return_value = CLIResult(success=True, message="ok", data={"usage": []})
    with patch_run(handler):
        code = run(["usage"])
    assert code == 0
    handler.token_usage.assert_called_once()


def test_workspace_write_command_calls_handler():
    handler = make_handler_mock()
    handler.workspace_write.return_value = CLIResult(success=True, message="ok", data={"path": "a.txt"})
    with patch_run(handler):
        code = run(["workspace", "write", "a.txt", "Hallo"])
    assert code == 0
    handler.workspace_write.assert_called_once_with("a.txt", "Hallo")


def test_backup_command_calls_handler(tmp_path):
    handler = make_handler_mock()
    handler.create_backup.return_value = CLIResult(success=True, message="ok", data={"backup_path": "b.zip"})
    with patch_run(handler):
        code = run(["backup", "--dir", str(tmp_path)])
    assert code == 0
    handler.create_backup.assert_called_once()


def test_web_command_opens_browser():
    with patch("conclave.cli.main.open_browser") as open_browser:
        code = run(["web", "--url", "http://127.0.0.1:8123"])
    assert code == 0
    open_browser.assert_called_once_with("http://127.0.0.1:8123")


def test_server_command_uses_runtime_path():
    with patch("conclave.cli.main._run_server", return_value=0) as server:
        code = run(["server", "--port", "8123"])
    assert code == 0
    server.assert_called_once()
