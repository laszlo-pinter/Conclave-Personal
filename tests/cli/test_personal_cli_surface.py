import pytest

from conclave.cli.main import build_parser


@pytest.mark.parametrize("command", [
    "consent-grant",
    "consent-revoke",
    "dpa-register",
    "dpa-list",
    "purge",
])
def test_enterprise_commands_are_not_registered(command):
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([command])


def test_parser_has_export():
    parser = build_parser()
    args = parser.parse_args(["export", "conv-1"])
    assert args.command == "export"
    assert args.conversation_id == "conv-1"


def test_parser_has_runs():
    parser = build_parser()
    args = parser.parse_args(["runs", "--conversation-id", "conv-1", "--limit", "10"])
    assert args.command == "runs"
    assert args.conversation_id == "conv-1"
    assert args.limit == 10


def test_parser_has_runtime_commands():
    parser = build_parser()
    assert parser.parse_args(["server", "--host", "127.0.0.1", "--port", "8123"]).command == "server"
    assert parser.parse_args(["web", "--url", "http://127.0.0.1:8123"]).command == "web"
    assert parser.parse_args(["desktop", "--port", "8123"]).command == "desktop"


def test_parser_has_workspace_commands():
    parser = build_parser()
    assert parser.parse_args(["workspace", "list"]).workspace_command == "list"
    read = parser.parse_args(["workspace", "read", "notes.md"])
    assert read.workspace_command == "read"
    assert read.path == "notes.md"
    write = parser.parse_args(["workspace", "write", "notes.md", "Hallo"])
    assert write.workspace_command == "write"
    assert write.content == "Hallo"


def test_parser_has_usage_backup_agent_test_and_auto_loop():
    parser = build_parser()
    assert parser.parse_args(["usage", "--by-conversation"]).by_conversation is True
    assert parser.parse_args(["backup", "--dir", "out"]).backup_dir == "out"
    restore = parser.parse_args(["restore", "--backup", "backup.zip", "--keep-workspace"])
    assert restore.command == "restore"
    assert restore.backup_path == "backup.zip"
    assert restore.keep_workspace is True
    assert parser.parse_args(["migrate-personal", "--from", "old.db"]).source_path == "old.db"
    assert parser.parse_args(["agent-test", "a1"]).id == "a1"
    loop = parser.parse_args([
        "auto-loop", "conv-1", "a", "b",
        "--max-rounds", "3",
        "--rotation", "round-robin",
    ])
    assert loop.command == "auto-loop"
    assert loop.participants == ["a", "b"]
    assert loop.max_rounds == 3
    assert loop.rotation == "round-robin"
