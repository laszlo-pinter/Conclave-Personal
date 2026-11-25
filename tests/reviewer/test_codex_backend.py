"""conclave#152: ``codex exec`` als zweites Backend des Reviewers.

- Kommandozeile: nur feste Schalter, Pfade und die MCP-Server; read-only, keine Benutzerkonfiguration, keine
  Rueckfragen, Auftrag aus stdin; kein Ticket-Text, kein Zeilenumbruch (wie R1).
- Die MCP-Angaben (``-c mcp_servers.…``) sind gueltiges TOML und ergeben genau die Server von ``mcp_servers``,
  das Board nur mit dem Reviewer-Token.
- stdin: System-Prompt, Hinweis zur Umgebung, Auftrag.
- Konfiguration: ``agent`` (claude oder codex), ``codex_exe``, ``codex_model``.
"""

import json
import os
import sys
import tomllib
from pathlib import Path

import pytest

from conclave.reviewer import command, config

CFG = {"conclave_url": "http://127.0.0.1:8000", "conclave_mcp_exe": "C:\\Program Files\\x\\conclave-mcp.exe",
       "author": "CD · auto-review", "codex_exe": "codex", "agent": "codex"}
WORKTREE = os.path.join("work", "worktrees", "api-1")      # Trenner der Plattform (Linux in der CI)
TEAM = os.path.join(WORKTREE, "_repos", "team")
DANGEROUS = ("--dangerously-bypass-approvals-and-sandbox", "--full-auto", "workspace-write", "danger-full-access",
             "--add-dir", "--dangerously-bypass-hook-trust", "--trust", "--approve-for-me")


def _servers(tmp_path):
    return command.mcp_servers(CFG, [WORKTREE, TEAM], tmp_path / "reviewer.token")


def _configs(cmd):
    return [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-c"]


def test_codex_runs_read_only_without_user_config_and_reads_the_ask_from_stdin(tmp_path):
    cmd = command.codex_command(CFG, worktree=WORKTREE, servers=_servers(tmp_path))
    assert cmd[:2] == ["codex", "exec"] and cmd[-1] == "-"
    assert "--ignore-user-config" in cmd and "--ephemeral" in cmd
    assert cmd[cmd.index("-s") + 1] == "read-only" and cmd[cmd.index("-C") + 1] == WORKTREE
    assert 'approval_policy="never"' in _configs(cmd)
    assert not any(bad in arg for arg in cmd for bad in DANGEROUS)
    assert "-m" not in cmd
    assert not any(ch in arg for arg in cmd for ch in "\r\n\0")


def test_mcp_servers_reach_codex_as_valid_toml(tmp_path):
    servers = _servers(tmp_path)["mcpServers"]
    cmd = command.codex_command(CFG, worktree=WORKTREE, servers={"mcpServers": servers})
    got = {}
    for item in _configs(cmd):
        key, _, raw = item.partition("=")
        if key.startswith("mcp_servers."):
            _, name, field = key.split(".")
            got.setdefault(name, {})[field] = tomllib.loads(f"v = {raw}")["v"]
    assert got == {name: {k: v for k, v in server.items()} for name, server in servers.items()}
    assert got["conclave"]["env"]["CONCLAVE_MCP_ROLE"] == "reviewer"
    assert set(got) == {"conclave", "git", "git_team"}
    text = json.dumps(got)
    for forbidden in ("agent.token", "api.token", "CONCLAVE_AGENT", "CONCLAVE_API_KEY"):
        assert forbidden not in text


def test_model_only_when_configured(tmp_path):
    cmd = command.codex_command({**CFG, "codex_model": "gpt-5-codex"}, worktree=WORKTREE, servers=_servers(tmp_path))
    assert cmd[cmd.index("-m") + 1] == "gpt-5-codex"


@pytest.mark.parametrize("title", ['Login & Logout | 50% "schneller"', "%PATH% --help", "Zeile1\nZeile2"])
def test_title_reaches_neither_command_line_nor_stdin(tmp_path, title):
    ask = command.review_ask("api#1", checked="main @ abc1234")
    stdin = command.codex_input("SYSTEM-PROMPT {nichts}", ask)
    cmd = command.codex_command(CFG, worktree=WORKTREE, servers=_servers(tmp_path))
    assert title not in stdin and all(title not in arg for arg in cmd)
    assert stdin.startswith("SYSTEM-PROMPT") and command.CODEX_NOTE in stdin and stdin.endswith(ask)


def test_command_line_and_stdin_arrive_unchanged(tmp_path):
    """Die TOML-Werte mit Anfuehrungszeichen und Backslashes ueberstehen die Windows-Kommandozeile unveraendert."""
    seen = tmp_path / "seen.json"
    echo = tmp_path / "echo.py"
    echo.write_text("import json, sys\n"                                  # UTF-8 wie Codex, nicht die Systemkodierung
                    f"open({str(seen)!r}, 'w', encoding='utf-8').write("
                    "json.dumps({'argv': sys.argv[1:], 'stdin': sys.stdin.buffer.read().decode('utf-8')}))\n",
                    encoding="utf-8")
    cmd = command.codex_command(CFG, worktree=WORKTREE, servers=_servers(tmp_path))
    stdin = command.codex_input("Prompt äöü ✓", command.review_ask("api#1", checked="main @ abc1234"))
    outcome = command.run_claude([sys.executable, str(echo), *cmd[1:]], str(tmp_path), 1, lambda m: None, "api#1",
                                 input_text=stdin)
    got = json.loads(seen.read_text(encoding="utf-8"))
    assert outcome == "done" and got["argv"] == cmd[1:]
    assert got["stdin"].replace("\r\n", "\n") == stdin


# ── Konfiguration ────────────────────────────────────────────────────────

def _load(tmp_path, extra=""):
    path = tmp_path / "config.toml"
    path.write_text(f"[reviewer]\n{extra}\n[reviewer.projects]\napi = 'C:/repo'\n", encoding="utf-8")
    return config.load(path)


def test_claude_stays_the_default(tmp_path):
    cfg = _load(tmp_path)
    assert (cfg["agent"], cfg["codex_exe"], cfg["codex_model"]) == ("claude", None, "")


def test_codex_is_chosen_with_agent(tmp_path):
    cfg = _load(tmp_path, 'agent = "codex"\ncodex_exe = "C:/codex/codex.exe"\ncodex_model = "gpt-5-codex"')
    assert (cfg["agent"], cfg["codex_exe"], cfg["codex_model"]) == ("codex", "C:/codex/codex.exe", "gpt-5-codex")


@pytest.mark.parametrize("extra, message", [('agent = "gemini"', "agent"), ("codex_exe = 3", "codex_exe"),
                                            ("codex_model = true", "codex_model")])
def test_unknown_agent_or_wrong_values_are_refused(tmp_path, extra, message):
    with pytest.raises(config.ConfigError, match=message):
        _load(tmp_path, extra)


def test_codex_from_the_newest_vscode_extension(tmp_path, monkeypatch):
    for version in ("26.1120.41243", "26.1121.7", "26.999.1"):                 # numerisch, nicht als Text
        exe = tmp_path / ".vscode" / "extensions" / f"openai.chatgpt-{version}-win32-x64" / "bin" / "windows-x86_64"
        exe.mkdir(parents=True)
        (exe / "codex.exe").write_bytes(b"")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert "openai.chatgpt-26.1121.7-" in command.find_codex({})
    assert command.find_codex({"codex_exe": "D:/eigen/codex.exe"}) == "D:/eigen/codex.exe"


def test_codex_gets_only_a_clean_environment():
    """Review V2: Codex hat eine Shell; keine CONCLAVE_*-Variablen, keine Schluessel, nur Pfade und System."""
    environ = {"PATH": "C:\\bin", "SystemRoot": "C:\\Windows", "APPDATA": "C:\\A", "CODEX_HOME": "C:\\c",
               "CONCLAVE_DB_DSN": "host=x", "CONCLAVE_API_KEY": "cvh_x", "OPENAI_API_KEY": "sk-x",
               "ANTHROPIC_API_KEY": "sk-ant", "CLAUDE_CODE_OAUTH_TOKEN": "t", "GITHUB_TOKEN": "g", "EIGENE": "e"}
    env = command.codex_env({}, environ)
    assert env == {"PATH": "C:\\bin", "SystemRoot": "C:\\Windows", "APPDATA": "C:\\A", "CODEX_HOME": "C:\\c"}
    assert command.codex_env({"codex_pass_env": ["eigene"]}, environ)["EIGENE"] == "e"      # ausdruecklich


def test_the_clean_environment_reaches_the_child(tmp_path, monkeypatch):
    seen = tmp_path / "env.json"
    echo = tmp_path / "echo.py"
    echo.write_text(f"import json, os; open({str(seen)!r}, 'w').write(json.dumps(sorted(os.environ)))",
                    encoding="utf-8")
    monkeypatch.setenv("CONCLAVE_SECRET_DEMO", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "y")
    outcome = command.run_claude([sys.executable, str(echo)], str(tmp_path), 1, lambda m: None, "api#1",
                                 env=command.codex_env({}))
    names = {n.upper() for n in json.loads(seen.read_text())}
    assert outcome == "done" and "PATH" in names
    assert "CONCLAVE_SECRET_DEMO" not in names and "OPENAI_API_KEY" not in names


def test_codex_under_the_own_user_is_warned_about(tmp_path, monkeypatch):
    """Review V3: Darf das Konto das Mensch- oder Agent-Token lesen, warnen Log und Status (nur Zugriffsrecht)."""
    from conclave.reviewer import status
    api, agent = tmp_path / "api.token", tmp_path / "agent.token"
    monkeypatch.setenv("CONCLAVE_API_TOKEN_FILE", str(api))
    monkeypatch.setenv("CONCLAVE_AGENT_TOKEN_FILE", str(agent))
    assert config.codex_account_warning() is None                                   # keine Dateien
    agent.write_text("cva_x\n", encoding="utf-8")
    warning = config.codex_account_warning()
    assert "agent.token" in warning and "api.token" not in warning and "eigenen Windows-Konto" in warning
    info = status.collect({"agent": "codex", "codex_exe": sys.executable}, tmp_path)
    assert f"WARNUNG: {warning}" in status.format_status(info)
    assert "account_warning" not in status.collect({"agent": "claude", "claude_exe": sys.executable}, tmp_path,
                                                    check_claude=False)


def _deny_read(path: Path) -> bool:
    """Die Datei fuer das eigene Konto unlesbar machen; False, wenn das hier nicht geht."""
    import getpass
    import os
    import subprocess
    if os.name == "nt":
        done = subprocess.run(["icacls", str(path), "/deny", f"{getpass.getuser()}:(R)"], capture_output=True)
        return done.returncode == 0
    path.chmod(0)
    return not os.access(path, os.R_OK)               # root liest trotzdem


def _allow_read(path: Path) -> None:
    import getpass
    import os
    import subprocess
    if os.name == "nt":
        subprocess.run(["icacls", str(path), "/remove:d", getpass.getuser()], capture_output=True)
    else:
        path.chmod(0o600)


def test_an_unreadable_token_file_gives_no_warning(tmp_path, monkeypatch):
    """Review V1: Unter Windows beachtet os.access keine Rechtelisten; die Pruefung oeffnet die Datei."""
    agent = tmp_path / "agent.token"
    agent.write_text("cva_x\n", encoding="utf-8")
    monkeypatch.setenv("CONCLAVE_API_TOKEN_FILE", str(tmp_path / "fehlt.token"))
    monkeypatch.setenv("CONCLAVE_AGENT_TOKEN_FILE", str(agent))
    assert "agent.token" in config.codex_account_warning()
    if not _deny_read(agent):
        pytest.skip("Lesesperre auf dieser Plattform nicht setzbar")
    try:
        assert config.codex_account_warning() is None
    finally:
        _allow_read(agent)


def test_codex_pass_env_must_be_a_list_of_names(tmp_path):
    with pytest.raises(config.ConfigError, match="codex_pass_env"):
        _load(tmp_path, 'codex_pass_env = "FOO"')
    assert _load(tmp_path, 'codex_pass_env = ["FOO"]')["codex_pass_env"] == ["FOO"]


def test_status_names_codex_instead_of_claude(tmp_path):
    from conclave.reviewer import status
    # Ein beliebiges Programm mit --version genuegt fuer die Anzeige; hier das Python der Tests
    info = status.collect({"agent": "codex", "codex_exe": sys.executable}, tmp_path)
    assert "claude_version" not in info and info["codex_version"] and info["codex_warning"] is None
    text = status.format_status(info)
    assert f"codex: {info['codex_version']}" in text and "claude:" not in text
    missing = status.collect({"agent": "codex", "codex_exe": str(tmp_path / "fehlt.exe")}, tmp_path)
    assert missing["codex_version"] is None and "codex nicht gefunden" in missing["codex_warning"]


def test_without_codex_the_reviewer_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(command.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit, match="codex_exe"):
        command.find_codex({})
