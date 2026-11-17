"""Der Aufruf von ``claude -p`` fuer ein Review: Tools, Verbote, MCP-Konfiguration.

Absicherung (durch Tests festgeschrieben, tests/reviewer/test_hardening.py):
- ``--restricted``: keine Shell, Benutzer- und Projekteinstellungen gelten nicht (deren Freigaben
  griffen sonst), Datei-Tools nur im Checkout.
- Tools genau ``Read,Grep,Glob`` plus die git-Tools und die drei Board-Tools des Reviewers;
  ``DENIED_ALWAYS`` und alle uebrigen Board-Tools sind ausdruecklich verboten.
- git nur ueber ``git_mcp`` (schreibgeschuetzt, mit ``python -I`` gestartet).
- Das Board nur ueber ``conclave-mcp --reviewer`` mit dem Reviewer-Token, nie mit dem Agent- oder
  Mensch-Token.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

GIT_MCP = Path(__file__).resolve().with_name("git_mcp.py")

BUILTIN_TOOLS = "Read,Grep,Glob"
GIT_TOOLS = ["mcp__git__status", "mcp__git__branches", "mcp__git__log", "mcp__git__show",
             "mcp__git__diff", "mcp__git__file"]
DENIED_ALWAYS = ["Bash", "PowerShell", "Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch"]

BOARDS = {
    "conclave": {
        "name": "Conclave-Board",
        "get": "conclave_board_get", "comment": "conclave_board_review", "comment_args": "",
        # conclave-mcp --reviewer bietet nur diese drei; das Ergebnis geht ueber review.
        "allowed": ["mcp__conclave__conclave_board_get", "mcp__conclave__conclave_board_list",
                    "mcp__conclave__conclave_board_review"],
        # Trotzdem verboten, falls der Server mehr anbietet als erwartet.
        "denied": [f"mcp__conclave__{t}" for t in (
            "conclave_board_comment", "conclave_board_next", "conclave_board_create", "conclave_board_update",
            "conclave_create_conversation", "conclave_list_conversations", "conclave_get_conversation",
            "conclave_add_participant", "conclave_send_message", "conclave_get_messages", "conclave_invoke",
            "conclave_orchestrate", "conclave_list_agents", "conclave_get_usage", "conclave_export_conversation",
            "conclave_list_files", "conclave_read_file", "conclave_upload_file", "conclave_consult",
            "conclave_get_consultation")],
    },
}


def find_claude(cfg: dict) -> str:
    if cfg.get("claude_exe"):
        return cfg["claude_exe"]
    # Die VS-Code-Erweiterung bringt claude.exe mit; die neueste installierte Version nehmen.
    ext = Path.home() / ".vscode" / "extensions"
    found = []
    for exe in ext.glob("anthropic.claude-code-*/resources/native-binary/claude.exe"):
        m = re.search(r"claude-code-(\d+)\.(\d+)\.(\d+)", str(exe))
        if m:
            found.append((tuple(map(int, m.groups())), exe))
    if found:
        return str(max(found)[1])
    on_path = shutil.which("claude")                  # Linux/macOS oder eigene Installation
    if on_path:
        return on_path
    raise SystemExit("claude nicht gefunden; claude_exe in config.toml setzen")


def child_python() -> str:
    """pythonw hat kein brauchbares stdio fuer einen Kindserver; dann python.exe daneben."""
    exe = Path(sys.executable)
    if exe.name.lower().startswith("pythonw"):
        return str(exe.with_name("python.exe"))
    return str(exe)


def mcp_servers(cfg: dict, repos: list[str], token_file: Path) -> dict:
    """Ein schreibgeschuetzter git-Server je Checkout ("git", dann git_<name>) und das Board als Reviewer."""
    from conclave.reviewer.refs import git_server
    python = child_python()
    servers = {git_server(i, r): {"command": python, "args": ["-I", str(GIT_MCP), "--repo", r]}
               for i, r in enumerate(repos)}
    servers["conclave"] = {"command": cfg["conclave_mcp_exe"],
                           "args": list(cfg.get("conclave_mcp_args", ["--reviewer"])), "env": {
        "CONCLAVE_API_URL": cfg["conclave_url"], "CONCLAVE_MCP_ROLE": "reviewer",
        "CONCLAVE_REVIEWER_TOKEN_FILE": str(token_file)}}
    return {"mcpServers": servers}


def prompt(cfg: dict, base_dir: Path) -> str:
    b = BOARDS["conclave"]
    text = (base_dir / cfg.get("prompt_file", "reviewer-prompt-conclave.md")).read_text(encoding="utf-8")
    for key, value in (("{author}", cfg["author"]), ("{board}", b["name"]), ("{get}", b["get"]),
                       ("{comment}", b["comment"]), ("{comment_args}", b["comment_args"])):
        text = text.replace(key, value)
    return text


def review_command(cfg: dict, task: dict, key: str, *, mcp_config: Path, prompt_text: str, checked: str = "",
                   extra=(), missing=()) -> list[str]:
    """``extra``: weitere Repos als (Name, Verzeichnis relativ zum Arbeitsverzeichnis, git-Server)."""
    b = BOARDS["conclave"]
    ask = f"Reviewe das Ticket {key}: {task['title']}"
    if checked:
        ask += f"\nGepruefter Stand (dein Arbeitsverzeichnis, ein eigener Worktree): {checked}"
    for name, rel, server in extra:
        ask += f"\nWeiteres Repo {name}: Verzeichnis {rel} in deinem Arbeitsverzeichnis, git ueber den Server {server}"
    if missing:
        ask += ("\nIn keinem lokalen Repo gefunden (dazu nicht pruefbar, Urteil hoechstens gelb): "
                + ", ".join(f"`{h}`" for h in missing))
    git_tools = [t.replace("mcp__git__", f"mcp__{server}__") for _n, _r, server in extra for t in GIT_TOOLS]
    return [
        find_claude(cfg), "-p", ask,
        "--restricted", "--tools", BUILTIN_TOOLS,
        "--append-system-prompt", prompt_text,
        "--mcp-config", str(mcp_config), "--strict-mcp-config",
        "--allowedTools", *BUILTIN_TOOLS.split(","), *GIT_TOOLS, *git_tools, *b["allowed"],
        "--disallowedTools", *DENIED_ALWAYS, *b["denied"],
    ]


def write_mcp_config(path: Path, servers: dict) -> None:
    path.write_text(json.dumps(servers))


def run_claude(cmd: list[str], cwd: str, timeout_minutes: float, log, key: str) -> str:
    """Startet den Reviewer; liefert "done", "failed" oder "timeout"."""
    started = time.monotonic()
    try:
        out = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout_minutes * 60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        log(f"{key}: review stopped after {timeout_minutes} minutes")
        return "timeout"
    took = round(time.monotonic() - started)
    if out.returncode == 0:
        log(f"{key}: review done in {took}s: {out.stdout.strip()[-300:]!r}")
        return "done"
    log(f"{key}: review failed (exit {out.returncode}) in {took}s: {(out.stderr or out.stdout).strip()[-500:]!r}")
    return "failed"
