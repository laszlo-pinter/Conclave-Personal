"""``conclave-reviewer status`` und das Ende mit dem Desktop (W4).

``status`` liest nur lokal: ob die Sperre gehalten wird (laeuft ja/nein), die Statusdatei des
Reviewers (laufendes Ticket, letztes Ergebnis), die Reviews der letzten Stunde aus dem Zustand und
``claude --version``. Ein Token braucht es dafuer nicht.

``watch_parent``: Startet ``conclave desktop`` den Reviewer als Kindprozess, endet dieser, sobald
der Desktop weg ist (auch wenn der Desktop abstuerzt). Ein dabei abgebrochenes Review gibt der
naechste Start frei (W3).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from conclave.reviewer.lock import AlreadyRunning, ProcessLock

TESTED_CLAUDE_MAJOR = 2                                 # mit claude 2.x geprueft (2.1.326)


def claude_version(cfg: dict) -> tuple[str | None, str | None]:
    """(Version, Warnung). Warnung bei fehlendem claude oder einer anderen Hauptversion."""
    from conclave.reviewer.command import find_claude
    try:
        exe = find_claude(cfg)
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (SystemExit, OSError, subprocess.SubprocessError) as e:
        return None, f"claude nicht gefunden oder nicht startbar ({e})"
    text = (out.stdout or out.stderr).strip()
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    if not match:
        return text or None, "Version von claude nicht erkannt"
    if int(match.group(1)) != TESTED_CLAUDE_MAJOR:
        return match.group(0), (f"unbekannte Version von claude ({match.group(0)}); geprueft ist "
                                f"{TESTED_CLAUDE_MAJOR}.x")
    return match.group(0), None


def is_running(lock_file: Path) -> bool:
    try:
        ProcessLock(lock_file).acquire().release()
    except AlreadyRunning:
        return True
    return False


def collect(cfg: dict, data_dir: Path, *, check_claude: bool = True) -> dict:
    def read(name):
        try:
            return json.loads((data_dir / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    running = is_running(data_dir / "reviewer.lock")
    status, state = read("status.json"), read("state.json")
    hour_ago = time.time() - 3600
    info = {"running": running, "data_dir": str(data_dir),
            "pid": status.get("pid") if running else None,
            "started_at": status.get("started_at") if running else None,
            "current_task": status.get("current_task") if running else None,
            "last_result": status.get("last_result"),
            "reviews_last_hour": len([t for t in state.get("reviews", []) if t > hour_ago])}
    if check_claude:
        info["claude_version"], info["claude_warning"] = claude_version(cfg)
    return info


def format_status(info: dict) -> str:
    lines = [f"Reviewer laeuft: {'ja' if info['running'] else 'nein'}"]
    if info["running"]:
        lines.append(f"  seit {info.get('started_at') or '?'} (PID {info.get('pid') or '?'})")
        lines.append(f"Laufendes Ticket: {info.get('current_task') or 'keins'}")
    last = info.get("last_result")
    lines.append(f"Letztes Ergebnis: {last['task']} {last['outcome']} ({last['at']})" if last else "Letztes Ergebnis: –")
    lines.append(f"Reviews in der letzten Stunde: {info['reviews_last_hour']}")
    if "claude_version" in info:
        lines.append(f"claude: {info['claude_version'] or '–'}")
        if info.get("claude_warning"):
            lines.append(f"WARNUNG: {info['claude_warning']}")
    lines.append(f"Datenordner: {info['data_dir']}")
    return "\n".join(lines)


# ── Ende mit dem Desktop ─────────────────────────────────────────────────

def process_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x00100000, False, pid)           # SYNCHRONIZE
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) != 0         # WAIT_OBJECT_0: beendet
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_for_exit_nt(pid: int) -> None:
    """Wartet auf das Ende von ``pid`` ueber ein einmal geoeffnetes Handle.

    Das Handle haelt den Prozess fest: Eine spaeter neu vergebene PID taeuscht nicht vor, er laufe
    noch. Laesst er sich gar nicht oeffnen, gilt er als beendet.
    """
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(0x00100000, False, pid)              # SYNCHRONIZE
    if not handle:
        return
    try:
        kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)               # INFINITE
    finally:
        kernel32.CloseHandle(handle)


def watch_parent(pid: int, on_gone, every: float = 2.0) -> threading.Thread:
    """Ruft ``on_gone()``, sobald der Prozess ``pid`` nicht mehr laeuft.

    Windows: Warten auf das Handle. POSIX: Ist ``pid`` der eigene Elternprozess, zaehlt der Wechsel
    von ``getppid()`` (keine Verwechslung mit einer neu vergebenen PID), sonst die Abfrage der PID.
    """
    def watch():
        if os.name == "nt":
            _wait_for_exit_nt(pid)
        elif os.getppid() == pid:
            while os.getppid() == pid:
                time.sleep(every)
        else:
            while process_alive(pid):
                time.sleep(every)
        on_gone()

    thread = threading.Thread(target=watch, name="reviewer-parent", daemon=True)
    thread.start()
    return thread
