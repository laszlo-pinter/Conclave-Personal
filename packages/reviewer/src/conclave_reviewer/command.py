"""Der Aufruf von ``claude -p`` fuer ein Review: Tools, Verbote, MCP-Konfiguration.

Absicherung (durch Tests festgeschrieben, tests/reviewer/test_hardening.py):
- ``--restricted``: keine Shell, Benutzer- und Projekteinstellungen gelten nicht (deren Freigaben
  griffen sonst), Datei-Tools nur im Checkout.
- Tools genau ``Read,Grep,Glob`` plus die git-Tools und die drei Board-Tools des Reviewers;
  ``DENIED_ALWAYS`` und alle uebrigen Board-Tools sind ausdruecklich verboten.
- git nur ueber ``git_mcp`` (schreibgeschuetzt, mit ``python -I`` gestartet).
- Das Board nur ueber ``conclave-mcp --reviewer`` mit dem Reviewer-Token, nie mit dem Agent- oder
  Mensch-Token. Am Team-Server (TR2) ueber ``conclave-board-mcp --reviewer``: dieselben drei Tools,
  derselbe Servername ``conclave`` in der MCP-Konfiguration, also dieselben erlaubten Tool-Namen.
"""

from __future__ import annotations

import json
import os
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
    from conclave_reviewer.refs import git_server
    python = child_python()
    servers = {git_server(i, r): {"command": python, "args": ["-I", str(GIT_MCP), "--repo", r]}
               for i, r in enumerate(repos)}
    servers["conclave"] = {"command": cfg["conclave_mcp_exe"],
                           "args": list(cfg.get("conclave_mcp_args", ["--reviewer"])), "env": board_env(cfg, token_file)}
    return {"mcpServers": servers}


def board_env(cfg: dict, token_file: Path) -> dict:
    """Umgebung des Board-MCP-Servers: nur Adresse, Rolle, Pfad der Token-Datei und CA (nie das Token)."""
    if cfg.get("server") == "team":                    # conclave-board-mcp (Team-Paket, TR2)
        env = {"CONCLAVE_BOARD_URL": cfg["conclave_url"], "CONCLAVE_BOARD_MCP_ROLE": "reviewer",
               "CONCLAVE_BOARD_TOKEN_FILE": str(token_file)}
        if cfg.get("ca_bundle"):
            env["CONCLAVE_BOARD_CA_BUNDLE"] = cfg["ca_bundle"]
        return env
    return {"CONCLAVE_API_URL": cfg["conclave_url"], "CONCLAVE_MCP_ROLE": "reviewer",
            "CONCLAVE_REVIEWER_TOKEN_FILE": str(token_file)}


def prompt(cfg: dict, base_dir: Path) -> str:
    """Alte Form (W1, config.toml des alten Watchers): Prompt-Datei relativ zu deren Ordner."""
    return fill_prompt(cfg, (base_dir / cfg.get("prompt_file", "reviewer-prompt-conclave.md")).read_text(encoding="utf-8"))


def fill_prompt(cfg: dict, text: str) -> str:
    b = BOARDS["conclave"]
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


# ── claude endet mit dem Reviewer (W4-Review B1) ───────────────────────────
#
# Windows: claude laeuft in einem Job-Objekt mit KILL_ON_JOB_CLOSE. Das Handle haelt nur dieser
# Prozess; endet er (normal, TerminateProcess, os._exit), schliesst Windows das Job-Objekt und
# beendet claude samt allen Kindprozessen. POSIX: eigene Prozessgruppe, die ``kill_claude`` beendet
# (beim Ende mit dem Desktop und bei SIGTERM).

_JOB = None


def _windows_job():
    global _JOB
    if _JOB is None:
        import ctypes
        from ctypes import wintypes

        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("Basic", Basic), ("IoInfo", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, ctypes.c_uint]
        job = kernel32.CreateJobObjectW(None, None)
        info = Extended()
        info.Basic.LimitFlags = 0x2000                     # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not job or not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError(ctypes.get_last_error(), "Job-Objekt fuer claude nicht angelegt")
        _JOB = (kernel32, job)
    return _JOB


def start_claude(cmd: list[str], cwd: str) -> subprocess.Popen:
    """claude so starten, dass es den Reviewer nicht ueberlebt."""
    proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace",
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                            start_new_session=os.name != "nt")
    if os.name == "nt":
        kernel32, job = _windows_job()
        if not kernel32.AssignProcessToJobObject(job, int(proc._handle)):
            proc.kill()
            raise OSError("claude nicht ins Job-Objekt gelegt")
    return proc


def kill_claude(proc: subprocess.Popen | None) -> None:
    """claude samt Kindprozessen beenden."""
    if proc is None or proc.poll() is not None:
        return
    if os.name == "nt":
        kernel32, job = _windows_job()
        kernel32.TerminateJobObject(job, 1)               # im Job sind nur claude-Prozesse
    else:
        import signal
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        proc.kill()


POLL_SECONDS = 0.2


def _wait_for(proc: subprocess.Popen, timeout: float) -> tuple[str, str]:
    """Wie ``communicate(timeout=...)``, aber unterbrechbar (TR3-Review V1).

    ``communicate`` wartet unter Windows ununterbrechbar auf seine Lesethreads; ein Stopp-Signal
    (Strg+Untbr eines Dienst-Wrappers) kaeme erst nach dem Ende von claude an. Hier lesen zwei Threads
    stdout und stderr, und der Hauptthread wartet in kurzen Schritten: Signale kommen sofort an."""
    import threading
    out, err = [], []
    readers = [threading.Thread(target=lambda s=stream, sink=sink: sink.append(s.read() if s else ""), daemon=True)
               for stream, sink in ((proc.stdout, out), (proc.stderr, err))]
    for reader in readers:
        reader.start()
    deadline = time.monotonic() + timeout
    while proc.poll() is None:
        if time.monotonic() >= deadline:
            raise subprocess.TimeoutExpired(proc.args, timeout)
        time.sleep(POLL_SECONDS)
    for reader in readers:
        reader.join(10)
    return "".join(out), "".join(err)


def run_claude(cmd: list[str], cwd: str, timeout_minutes: float, log, key: str, on_start=None,
               quiet: bool = False) -> str:
    """Startet den Reviewer; liefert "done", "failed" oder "timeout". ``on_start(proc)`` meldet den Prozess.

    ``quiet`` (Team-Server, TR3): die Ausgabe von claude nicht ins Log, sie kann Text aus dem Review und
    damit aus Tickets enthalten; bei einem Fehler nur stderr (Meldungen von claude selbst)."""
    started = time.monotonic()
    proc = start_claude(cmd, cwd)
    if on_start is not None:
        on_start(proc)
    try:
        stdout, stderr = _wait_for(proc, timeout_minutes * 60)
    except subprocess.TimeoutExpired:
        kill_claude(proc)                               # samt Kindprozessen, nicht nur der oberste Prozess
        log(f"{key}: review stopped after {timeout_minutes} minutes")
        return "timeout"
    except BaseException:
        # Strg+C oder ein anderer Abbruch mitten im Review (TR3-Review B1): claude zuerst beenden, solange
        # der Prozess noch bekannt ist; danach entfernt der Aufrufer die Worktrees
        kill_claude(proc)
        raise
    took = round(time.monotonic() - started)
    if proc.returncode == 0:
        log(f"{key}: review done in {took}s" + ("" if quiet else f": {stdout.strip()[-300:]!r}"))
        return "done"
    detail = (stderr or "").strip()[-500:] if quiet else (stderr or stdout).strip()[-500:]
    log(f"{key}: review failed (exit {proc.returncode}) in {took}s: {detail!r}")
    return "failed"
