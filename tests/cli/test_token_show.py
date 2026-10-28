"""Z5: `conclave token show` zeigt Pfade und Einrichtung, den Wert nur mit --reveal."""

from conclave.cli.main import run
from conclave.runtime import api_token


def test_agent_shows_path_and_command_without_value(tmp_path, capsys):
    assert run(["token", "show", "--agent"]) == 0
    out = capsys.readouterr().out
    token = (tmp_path / "agent.token").read_text(encoding="utf-8").strip()   # angelegt (conftest-Pfad)
    assert token.startswith("cva_") and token not in out
    assert str(tmp_path / "agent.token") in out and "neu angelegt" in out
    assert "claude mcp add Conclave" in out and "CONCLAVE_AGENT_KEY=<Inhalt von agent.token>" in out


def test_agent_reveal_prints_value(tmp_path, capsys):
    token = api_token.load_or_create_agent_token(tmp_path / "agent.token")
    assert run(["token", "show", "--agent", "--reveal"]) == 0
    out = capsys.readouterr().out
    assert f"CONCLAVE_AGENT_KEY={token}" in out and "neu angelegt" not in out


def test_agent_key_from_environment_is_used(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CONCLAVE_AGENT_KEY", "cva_aus_env")
    assert run(["token", "show", "--agent"]) == 0
    out = capsys.readouterr().out
    assert "Agent-Token: CONCLAVE_AGENT_KEY" in out and "cva_aus_env" not in out
    assert not (tmp_path / "agent.token").exists()


def test_human_token_value_only_with_reveal(tmp_path, capsys):
    token = api_token.load_or_create_token(tmp_path / "api.token")
    assert run(["token", "show"]) == 0
    out = capsys.readouterr().out
    assert str(tmp_path / "api.token") in out and token not in out
    assert "Nie in eine MCP" in out
    assert run(["token", "show", "--reveal"]) == 0
    assert token in capsys.readouterr().out
