"""Der Aufruf von ``claude -p`` fuer ein Review: Tools, Verbote, MCP-Konfiguration.

Absicherung (durch Tests festgeschrieben, tests/reviewer/test_hardening.py):
- ``--restricted``: keine Shell, Benutzer- und Projekteinstellungen gelten nicht (deren Freigaben
  griffen sonst), Datei-Tools nur im Checkout.
- Tools genau ``Read,Grep,Glob`` plus die git-Tools und die drei Board-Tools des Reviewers;
  ``DENIED_ALWAYS`` und alle uebrigen Board-Tools sind ausdruecklich verboten.
- git nur ueber ``git_mcp`` (schreibgeschuetzt, mit ``python -I`` gestartet).
- Das Board nur ueber ``conclave-mcp --reviewer`` mit dem Reviewer-Token, nie mit dem Agent- oder
  Mensch-Token. An einem entfernten Board-Server (TR2) ueber ``conclave-board-mcp --reviewer``: dieselben drei Tools,
  derselbe Servername ``conclave`` in der MCP-Konfiguration, also dieselben erlaubten Tool-Namen.
- Kein Ticket-Text und kein mehrzeiliger Text auf der Kommandozeile (R1, conclave#142): Den Auftrag bekommt
  ``claude -p`` ueber stdin (ohne den Titel, er ist fremder Text; der Reviewer liest das Ticket selbst), den
  System-Prompt ueber ``--append-system-prompt-file``. Ist ``claude`` ein ``.cmd``/``.bat`` (npm), schnitte
  ``cmd.exe`` sonst am ersten Zeilenumbruch ab, und alle Schutzschalter dahinter fehlten.
- Wahlweise ``codex exec`` statt claude (``agent = "codex"``, conclave#152), siehe ``codex_command``.
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
    if cfg.get("server") == "team":                    # conclave-board-mcp (Board-Server mit Konten, TR2)
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


def review_ask(key: str, *, checked: str = "", extra=(), missing=()) -> str:
    """Der Auftrag an ``claude -p``, ueber stdin (R1). Ohne den Titel: Er ist fremder Text, kann beliebige
    Zeichen enthalten und steht ohnehin im Ticket, das der Reviewer mit ``conclave_board_get`` liest."""
    ask = f"Reviewe das Ticket {key}. Lies es zuerst mit {BOARDS['conclave']['get']}."
    if checked:
        ask += f"\nGepruefter Stand (dein Arbeitsverzeichnis, ein eigener Worktree): {checked}"
    for name, rel, server in extra:
        ask += f"\nWeiteres Repo {name}: Verzeichnis {rel} in deinem Arbeitsverzeichnis, git ueber den Server {server}"
    if missing:
        ask += ("\nIn keinem lokalen Repo gefunden (dazu nicht pruefbar, Urteil hoechstens gelb): "
                + ", ".join(f"`{h}`" for h in missing))
    return ask + "\n"


def review_command(cfg: dict, *, mcp_config: Path, prompt_file: Path, extra=()) -> list[str]:
    """Die Kommandozeile von ``claude``: nur feste Schalter, Tool-Namen und Pfade, nie Text aus einem Ticket (R1).

    ``extra``: weitere Repos als (Name, Verzeichnis relativ zum Arbeitsverzeichnis, git-Server). Den Auftrag
    (``review_ask``) bekommt claude ueber stdin, den System-Prompt aus ``prompt_file``."""
    b = BOARDS["conclave"]
    git_tools = [t.replace("mcp__git__", f"mcp__{server}__") for _n, _r, server in extra for t in GIT_TOOLS]
    cmd = [
        find_claude(cfg), "-p",
        "--restricted", "--tools", BUILTIN_TOOLS,
        "--append-system-prompt-file", str(prompt_file),
        "--mcp-config", str(mcp_config), "--strict-mcp-config",
        "--allowedTools", *BUILTIN_TOOLS.split(","), *GIT_TOOLS, *git_tools, *b["allowed"],
        "--disallowedTools", *DENIED_ALWAYS, *b["denied"],
    ]
    check_command_line(cmd)
    return cmd


# ── codex exec als zweites Backend (conclave#152) ───────────────────────────
#
# Codex hat immer eine Shell. ``-s read-only`` verbietet Schreiben, nicht Lesen: Die Sandbox liest alles, was
# das Konto lesen darf, und localhost ist erreichbar (conclave#150/#151). Conclaves eigene Token-Dateien
# schuetzen ihre Dateirechte; alles Weitere nur ein eigenes Konto ohne Zugangsdaten. ``--ignore-user-config``:
# keine Einstellungen und MCP-Server aus ~/.codex (die Anmeldung gilt weiter).

CODEX_NOTE = ("Hinweis zu deiner Umgebung: Du laeufst als codex exec in einer schreibgeschuetzten Sandbox. "
              "Abweichend vom Text oben hast du eine Shell; nutze sie nur zum Lesen von Dateien und fuer git im "
              "Arbeitsverzeichnis, nichts ausserhalb davon und kein Netz. Das Ergebnis setzt du wie beschrieben ueber "
              "das Board-Tool.")


def find_codex(cfg: dict) -> str:
    if cfg.get("codex_exe"):
        return cfg["codex_exe"]
    # Die VS-Code-Erweiterung von OpenAI bringt codex.exe mit; die neueste installierte Version nehmen.
    ext = Path.home() / ".vscode" / "extensions"
    found = []
    for exe in ext.glob("openai.chatgpt-*/bin/*/codex.exe"):
        m = re.search(r"chatgpt-(\d+)\.(\d+)\.(\d+)", str(exe))
        if m:
            found.append((tuple(map(int, m.groups())), exe))
    if found:
        return str(max(found)[1])
    on_path = shutil.which("codex")
    if on_path:
        return on_path
    raise SystemExit("codex nicht gefunden; codex_exe in config.toml setzen")


def _toml(value) -> str:
    """Ein Wert fuer ``-c key=value``: JSON-Strings (ASCII) sind gueltige TOML-Basic-Strings."""
    if isinstance(value, dict):
        return "{" + ", ".join(f"{json.dumps(k)} = {_toml(v)}" for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(_toml(v) for v in value) + "]"
    return json.dumps(value)


def codex_command(cfg: dict, *, worktree: str, servers: dict) -> list[str]:
    """Die Kommandozeile von ``codex exec``: nur feste Schalter, Pfade und die MCP-Server, nie Text aus einem
    Ticket (wie R1). Auftrag und System-Prompt kommen ueber stdin (``codex_input``)."""
    cmd = [find_codex(cfg), "exec", "--ignore-user-config", "--ephemeral", "--color", "never",
           "-s", "read-only", "-c", 'approval_policy="never"', "-C", worktree]
    if cfg.get("codex_model"):
        cmd += ["-m", cfg["codex_model"]]
    for name, server in servers["mcpServers"].items():
        cmd += ["-c", f"mcp_servers.{name}.command={_toml(server['command'])}",
                "-c", f"mcp_servers.{name}.args={_toml(list(server.get('args', [])))}"]
        if server.get("env"):
            cmd += ["-c", f"mcp_servers.{name}.env={_toml(server['env'])}"]
    cmd.append("-")                                     # Auftrag aus stdin
    check_command_line(cmd)
    return cmd


# Was Codex und seine MCP-Server zum Laufen brauchen; keine Schluessel, keine CONCLAVE_*-Variablen (Review V2):
# Codex hat eine Shell und koennte seine Umgebung auslesen. Mehr nur ueber ``codex_pass_env``.
CODEX_ENV = ("PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP", "USERPROFILE",
             "HOMEDRIVE", "HOMEPATH", "HOME", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES",
             "PROGRAMFILES(X86)", "PROGRAMW6432", "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)", "USERNAME",
             "USERDOMAIN", "COMPUTERNAME", "OS", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS", "USER", "LOGNAME",
             "LANG", "LC_ALL", "LC_CTYPE", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME",
             "XDG_RUNTIME_DIR", "CODEX_HOME", "PYTHONUSERBASE", "PYTHONPATH", "PYTHONIOENCODING", "PYTHONUTF8",
             "VIRTUAL_ENV")


def codex_env(cfg: dict, environ=None) -> dict:
    """Die Umgebung fuer ``codex exec``: nur ``CODEX_ENV`` und was ``codex_pass_env`` ausdruecklich nennt."""
    environ = os.environ if environ is None else environ
    keep = {name.upper() for name in (*CODEX_ENV, *(cfg.get("codex_pass_env") or ()))}
    return {name: value for name, value in environ.items() if name.upper() in keep}


def codex_input(prompt_text: str, ask: str) -> str:
    """System-Prompt, Hinweis zur Umgebung und Auftrag in einem Text fuer stdin (Codex hat keine Prompt-Datei)."""
    return f"{prompt_text.rstrip()}\n\n{CODEX_NOTE}\n\n---\n\n{ask}"


def check_command_line(cmd: list[str]) -> None:
    """Kein Zeilenumbruch und kein Nullzeichen in einem Argument: ``cmd.exe`` (claude als ``.cmd``) schnitte dort
    ab, und die Schutzschalter dahinter fehlten (R1)."""
    for arg in cmd:
        if any(ch in arg for ch in "\r\n\0"):
            raise ValueError(f"Argument fuer claude mit Zeilenumbruch abgelehnt: {arg[:40]!r}")


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


def start_claude(cmd: list[str], cwd: str, with_input: bool = False, env: dict | None = None) -> subprocess.Popen:
    """claude so starten, dass es den Reviewer nicht ueberlebt. ``with_input``: stdin als Pipe fuer den Auftrag.
    ``env``: eine eigene Umgebung (codex, Review V2); ``None`` erbt die des Reviewers."""
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.PIPE if with_input else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
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


def _feed(stream, text: str) -> None:
    """Den Auftrag schreiben und stdin schliessen; endet claude vorher, ist das kein Fehler des Reviewers."""
    try:
        stream.write(text)
        stream.close()
    except (BrokenPipeError, OSError, ValueError):
        pass


def _wait_for(proc: subprocess.Popen, timeout: float, input_text: str | None = None) -> tuple[str, str]:
    """Wie ``communicate(timeout=...)``, aber unterbrechbar (TR3-Review V1).

    ``communicate`` wartet unter Windows ununterbrechbar auf seine Lesethreads; ein Stopp-Signal
    (Strg+Untbr eines Dienst-Wrappers) kaeme erst nach dem Ende von claude an. Hier lesen zwei Threads
    stdout und stderr, und der Hauptthread wartet in kurzen Schritten: Signale kommen sofort an.
    ``input_text`` schreibt ein dritter Thread nach stdin (R1), damit eine volle Pipe nichts blockiert."""
    import threading
    out, err = [], []
    readers = [threading.Thread(target=lambda s=stream, sink=sink: sink.append(s.read() if s else ""), daemon=True)
               for stream, sink in ((proc.stdout, out), (proc.stderr, err))]
    if input_text is not None and proc.stdin is not None:
        threading.Thread(target=_feed, args=(proc.stdin, input_text), daemon=True).start()
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
               quiet: bool = False, input_text: str | None = None, env: dict | None = None) -> str:
    """Startet den Reviewer; liefert "done", "failed" oder "timeout". ``on_start(proc)`` meldet den Prozess.

    ``quiet`` (entfernter Server, TR3): die Ausgabe von claude nicht ins Log, sie kann Text aus dem Review und
    damit aus Tickets enthalten; bei einem Fehler nur stderr (Meldungen von claude selbst).
    ``input_text``: der Auftrag (``review_ask``), ueber stdin statt auf der Kommandozeile (R1)."""
    started = time.monotonic()
    # ohne Auftrag die alte Form des Aufrufs (Tests ersetzen start_claude mit genau zwei Argumenten)
    if env is not None:
        proc = start_claude(cmd, cwd, with_input=input_text is not None, env=env)
    elif input_text is not None:
        proc = start_claude(cmd, cwd, with_input=True)
    else:
        proc = start_claude(cmd, cwd)
    if on_start is not None:
        on_start(proc)
    try:
        stdout, stderr = _wait_for(proc, timeout_minutes * 60, input_text)
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
