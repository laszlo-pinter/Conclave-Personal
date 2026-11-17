"""``conclave desktop`` startet den Reviewer, wenn er konfiguriert ist (W4, Entscheidung E-W3 (b)).

Konfiguriert heisst: ``[reviewer]`` mit mindestens einem Projekt, ``enabled`` nicht ``false`` und die
Datei ``reviewer.token`` existiert (sie wird nur auf Vorhandensein geprueft, nie gelesen). Einen
Schalter ``autostart`` gibt es nicht.

Der Reviewer laeuft als Kindprozess ohne Konsole und endet mit dem Desktop: ueber ``--parent-pid``
auch dann, wenn der Desktop abstuerzt, und beim normalen Ende ueber ``stop_reviewer``. Haelt schon
ein Reviewer die Sperre (auch der alte Watcher mit ``watcher.lock``), startet kein zweiter; das Log
nennt jeweils den Grund.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def reviewer_configured() -> tuple[bool, str, dict | None]:
    """(konfiguriert, Grund, Konfiguration)."""
    from conclave.reviewer import config as rc
    path = rc.conclave_config_path()
    if not path.exists():
        return False, f"keine Konfiguration unter {path}", None
    try:
        cfg = rc.load(path)
    except rc.ConfigError as e:
        text = str(e)
        if "kein Abschnitt [reviewer]" in text:
            return False, "kein Abschnitt [reviewer] in der Konfiguration", None
        return False, f"[reviewer] unbrauchbar: {text}", None
    if not cfg["enabled"]:
        return False, "[reviewer] enabled = false", cfg
    if not Path(cfg["reviewer_token_file"]).exists():
        return False, f"reviewer.token fehlt ({cfg['reviewer_token_file']})", cfg
    return True, "konfiguriert", cfg


def already_running(cfg: dict) -> str | None:
    """Grund, warum kein zweiter Reviewer startet (Sperre gehalten), sonst None."""
    from conclave.reviewer.config import data_dir
    from conclave.reviewer.lock import AlreadyRunning, ProcessLock
    legacy = tuple(Path(p) for p in [cfg.get("legacy_lock_file")] if p)
    try:
        ProcessLock(data_dir() / "reviewer.lock", legacy=legacy).acquire().release()
    except AlreadyRunning as e:
        return str(e)
    return None


def start_reviewer(log) -> subprocess.Popen | None:
    """Startet ``conclave-reviewer run`` als Kindprozess, wenn konfiguriert und nicht schon laufend."""
    ok, reason, cfg = reviewer_configured()
    if not ok:
        log(f"Reviewer nicht gestartet: {reason}")
        return None
    running = already_running(cfg)
    if running:
        log(f"Reviewer nicht gestartet: {running}")
        return None
    from conclave.reviewer.config import data_dir
    folder = data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    errors = (folder / "reviewer-start.log").open("ab")          # nur Startfehler; das eigentliche Log fuehrt er selbst
    cmd = [sys.executable, "-m", "conclave.reviewer", "run", "--parent-pid", str(os.getpid())]
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), close_fds=True)
    errors.close()
    log(f"Reviewer gestartet (PID {proc.pid})")
    return proc


def stop_reviewer(proc: subprocess.Popen | None, timeout: float = 10.0) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
