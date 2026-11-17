"""W1 (#89): Die Absicherung des Reviewers, als Test festgeschrieben.

- Aufruf: ``--restricted``, Tools genau Read/Grep/Glob plus git- und Board-Tools des Reviewers,
  ``DENIED_ALWAYS`` und die uebrigen Board-Tools verboten.
- MCP-Konfiguration: das Board nur mit dem Reviewer-Token, nie Agent- oder Mensch-Token; git nur
  ueber ``git_mcp`` mit ``python -I``.
- ``git_mcp`` lehnt alles ab, was schreiben koennte.
- Sperre: hoechstens ein Reviewer, auch gegenueber dem alten Watcher; eine verwaiste Datei sperrt nicht.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conclave.reviewer import command, git_mcp
from conclave.reviewer.lock import AlreadyRunning, ProcessLock

CFG = {"conclave_url": "http://127.0.0.1:8000", "conclave_mcp_exe": "conclave-mcp", "author": "CD · auto-review",
       "claude_exe": "claude"}


def _option(cmd, name):
    start = cmd.index(name) + 1
    end = next((i for i in range(start, len(cmd)) if cmd[i].startswith("--")), len(cmd))
    return cmd[start:end]


def _cmd(extra=()):
    return command.review_command(CFG, {"title": "T"}, "api#1", mcp_config=Path("mcp.json"), prompt_text="P",
                                  checked="main @ abc1234", extra=extra)


# ── Aufruf ───────────────────────────────────────────────────────────────

def test_restricted_with_exactly_the_reviewer_tools():
    cmd = _cmd()
    assert "--restricted" in cmd and "--strict-mcp-config" in cmd
    assert _option(cmd, "--tools") == ["Read,Grep,Glob"]
    allowed = _option(cmd, "--allowedTools")
    assert allowed == ["Read", "Grep", "Glob", *command.GIT_TOOLS, *command.BOARDS["conclave"]["allowed"]]
    assert set(command.BOARDS["conclave"]["allowed"]) == {
        "mcp__conclave__conclave_board_get", "mcp__conclave__conclave_board_list",
        "mcp__conclave__conclave_board_review"}
    denied = _option(cmd, "--disallowedTools")
    assert set(command.DENIED_ALWAYS) <= set(denied)
    assert {"Bash", "PowerShell", "Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch"} <= set(denied)
    assert "mcp__conclave__conclave_board_update" in denied and "mcp__conclave__conclave_board_comment" in denied
    assert not set(allowed) & set(denied)
    assert all(t.startswith(("mcp__git__", "mcp__conclave__")) or t in ("Read", "Grep", "Glob") for t in allowed)


def test_further_repos_get_only_their_read_tools():
    allowed = _option(_cmd(extra=[("team", "_repos/team", "git_team")]), "--allowedTools")
    assert [t for t in allowed if t.startswith("mcp__git_team__")] == [
        t.replace("mcp__git__", "mcp__git_team__") for t in command.GIT_TOOLS]


# ── MCP-Konfiguration ────────────────────────────────────────────────────

def test_board_only_with_the_reviewer_token_and_git_isolated(tmp_path):
    token = tmp_path / "reviewer.token"
    servers = command.mcp_servers(CFG, ["/repo/a", "/repo/b"], token)["mcpServers"]
    board = servers["conclave"]
    assert board["args"] == ["--reviewer"]
    assert board["env"] == {"CONCLAVE_API_URL": CFG["conclave_url"], "CONCLAVE_MCP_ROLE": "reviewer",
                            "CONCLAVE_REVIEWER_TOKEN_FILE": str(token)}
    text = json.dumps(servers)
    for forbidden in ("agent.token", "api.token", "CONCLAVE_AGENT", "CONCLAVE_API_KEY", "CONCLAVE_API_TOKEN"):
        assert forbidden not in text
    for name, repo in (("git", "/repo/a"), ("git_b", "/repo/b")):
        assert servers[name]["args"] == ["-I", str(command.GIT_MCP), "--repo", repo]
    assert Path(command.GIT_MCP).name == "git_mcp.py" and Path(command.GIT_MCP).exists()


def test_child_python_is_not_pythonw(monkeypatch):
    monkeypatch.setattr(sys, "executable", str(Path("/opt/py/pythonw.exe")))
    assert Path(command.child_python()) == Path("/opt/py/python.exe")
    monkeypatch.setattr(sys, "executable", "/usr/bin/python3")
    assert Path(command.child_python()) == Path("/usr/bin/python3")


# ── git_mcp schreibt nichts ──────────────────────────────────────────────

@pytest.mark.parametrize("name, args", [
    ("commit", {}), ("push", {}), ("checkout", {}), ("reset", {}), ("config", {}),
    ("log", {"rev": "--output=/tmp/x"}), ("show", {"rev": "-o"}), ("diff", {"base": "a..b", "head": "c"}),
    ("file", {"rev": "HEAD", "path": "../draussen"}), ("file", {"rev": "HEAD", "path": "-x"}),
    ("log", {"max_count": 10_000}), ("status", {"extra": 1}),
])
def test_git_mcp_refuses_anything_that_could_write_or_escape(tmp_path, name, args):
    with pytest.raises(git_mcp.Refused):
        git_mcp.build(tmp_path, name, args)


def test_git_mcp_only_knows_read_commands():
    assert {t["name"] for t in git_mcp.TOOLS} == {"status", "branches", "log", "show", "diff", "file"}
    assert "diff.external=" in git_mcp.BASE and "--no-ext-diff" in git_mcp.DIFF_FLAGS


def test_git_mcp_runs_isolated_over_stdio(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "status", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "commit", "arguments": {}}}]
    out = subprocess.run([sys.executable, "-I", str(command.GIT_MCP), "--repo", str(repo)],
                         input="\n".join(json.dumps(m) for m in msgs) + "\n", capture_output=True, text=True,
                         timeout=60, cwd=tmp_path)
    replies = {r["id"]: r for r in map(json.loads, out.stdout.splitlines())}
    assert replies[2]["result"]["isError"] is False
    assert replies[3]["result"]["isError"] is True and "unbekanntes Tool" in replies[3]["result"]["content"][0]["text"]


# ── Sperre ───────────────────────────────────────────────────────────────

HOLD = """
import os, sys, time
f = open(sys.argv[1], "w")
if os.name == "nt":
    import msvcrt
    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
else:
    import fcntl
    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
print("locked", flush=True)
time.sleep(60)
"""


def _hold(path):
    """Ein fremder Prozess haelt die Sperre wie der alte Watcher (Windows: msvcrt, 1 Byte)."""
    proc = subprocess.Popen([sys.executable, "-c", HOLD, str(path)], stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "locked"
    return proc


def test_only_one_reviewer_per_data_dir(tmp_path):
    with ProcessLock(tmp_path / "reviewer.lock"):
        with pytest.raises(AlreadyRunning):
            ProcessLock(tmp_path / "reviewer.lock").acquire()
    ProcessLock(tmp_path / "reviewer.lock").acquire().release()               # danach wieder frei


def test_another_process_holding_the_lock_blocks(tmp_path):
    proc = _hold(tmp_path / "reviewer.lock")
    try:
        with pytest.raises(AlreadyRunning, match="conclave-reviewer"):
            ProcessLock(tmp_path / "reviewer.lock").acquire()
    finally:
        proc.kill()
        proc.wait(10)
    ProcessLock(tmp_path / "reviewer.lock").acquire().release()               # Prozess weg: Sperre weg


def test_running_old_watcher_blocks_the_new_reviewer(tmp_path):
    legacy = tmp_path / "watcher.lock"
    proc = _hold(legacy)
    try:
        with pytest.raises(AlreadyRunning, match="alte Watcher"):
            ProcessLock(tmp_path / "data" / "reviewer.lock", legacy=(legacy,)).acquire()
    finally:
        proc.kill()
        proc.wait(10)


def test_orphaned_lock_files_do_not_block(tmp_path):
    (tmp_path / "reviewer.lock").write_text("12345", encoding="utf-8")       # von einem abgestuerzten Lauf
    (tmp_path / "watcher.lock").write_text("", encoding="utf-8")
    lock = ProcessLock(tmp_path / "reviewer.lock", legacy=(tmp_path / "watcher.lock",)).acquire()
    lock.release()
    assert (tmp_path / "reviewer.lock").read_text(encoding="utf-8") == "12345"   # nie gekuerzt


@pytest.mark.skipif(os.name != "nt", reason="der alte Watcher lief nur unter Windows")
def test_old_watcher_cannot_start_while_the_new_one_runs(tmp_path):
    legacy = tmp_path / "watcher.lock"
    legacy.write_text("", encoding="utf-8")
    with ProcessLock(tmp_path / "reviewer.lock", legacy=(legacy,)):
        probe = subprocess.run([sys.executable, "-c", HOLD.replace("time.sleep(60)", ""), str(legacy)],
                               capture_output=True, text=True, timeout=60)
        assert probe.returncode != 0 and "locked" not in probe.stdout
