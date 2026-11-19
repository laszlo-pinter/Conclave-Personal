"""TR3 (conclave#125): Stoppen als Dienst.

Ein Dienst-Wrapper unter Windows schickt Strg+Untbr bzw. Strg+C, systemd SIGTERM. Der Reviewer beendet
dann erst claude samt Kindprozessen und die Worktrees, protokolliert das Ende und gibt die Sperre frei,
damit der Dienst sofort neu starten kann.
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conclave_reviewer import cli
from conclave_reviewer.lock import ProcessLock

ROOT = Path(__file__).resolve().parents[2]


def _settings(tmp_path: Path) -> Path:
    (tmp_path / "reviewer.token").write_text("cvr_x\n", encoding="utf-8")
    (tmp_path / "repo").mkdir()
    path = tmp_path / "reviewer.toml"
    path.write_text('[reviewer]\nconclave_url = "http://127.0.0.1:9"\nreviewer_token_file = "reviewer.token"\n'
                    'data_dir = "daten"\npoll_seconds = 1\nclaude_exe = "claude"\n'
                    f'[reviewer.projects]\napi = "{(tmp_path / "repo").as_posix()}"\n', encoding="utf-8")
    return path


def _wait(predicate, timeout=30.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.2)
    return False


def test_stop_signal_ends_the_reviewer_cleanly_and_frees_the_lock(tmp_path):
    settings = _settings(tmp_path)
    log = tmp_path / "daten" / "reviewer.log"
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(
        str(ROOT / part) for part in ("src", "packages/board/src", "packages/reviewer/src")))
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    proc = subprocess.Popen([sys.executable, "-m", "conclave_reviewer", "run", "--settings", str(settings)],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=flags)
    try:
        assert _wait(lambda: log.exists() and "board not reachable" in log.read_text(encoding="utf-8")), \
            proc.stderr.read() if proc.poll() is not None else "kein Log"
        proc.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
        assert proc.wait(30) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
    assert "stopped (signal)" in log.read_text(encoding="utf-8")
    ProcessLock(tmp_path / "daten" / "reviewer.lock").acquire().release()       # Neustart moeglich


def test_ctrl_c_shuts_down_claude_and_worktrees(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    calls = []
    monkeypatch.setattr(cli.Reviewer, "loop", lambda self, **kw: (_ for _ in ()).throw(KeyboardInterrupt()))
    monkeypatch.setattr(cli, "_shutdown", lambda reviewer: calls.append("shutdown"))
    monkeypatch.setattr(cli, "_stop_signals", lambda reviewer: None)
    assert cli.main(["run", "--settings", str(settings)]) == 0
    assert calls == ["shutdown"]
    assert "stopped (Ctrl+C)" in (tmp_path / "daten" / "reviewer.log").read_text(encoding="utf-8")


@pytest.mark.skipif(os.name != "nt", reason="Windows-Signal")
def test_windows_registers_ctrl_break(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(signal, "signal", lambda sig, handler: seen.setdefault(sig, handler))
    cli._stop_signals(object())
    assert signal.SIGBREAK in seen and signal.SIGTERM not in seen


@pytest.mark.parametrize("quiet", [True, False])
def test_team_log_has_no_output_of_claude(tmp_path, quiet):
    """TR3: Am Team-Server enthaelt das Log keine Ausgabe von claude (sie kann Ticket-Text enthalten)."""
    from conclave_reviewer import command
    lines = []
    script = "import sys; print('Urteil: gruen, Ticket-Text GEHEIM'); sys.exit(0)"
    assert command.run_claude([sys.executable, "-c", script], str(tmp_path), 1, lines.append, "api#1",
                              quiet=quiet) == "done"
    assert ("GEHEIM" in lines[-1]) is (not quiet)
    failing = "import sys; print('Ticket-Text GEHEIM'); print('claude: Anmeldung fehlt', file=sys.stderr); sys.exit(2)"
    assert command.run_claude([sys.executable, "-c", failing], str(tmp_path), 1, lines.append, "api#1",
                              quiet=quiet) == "failed"
    assert "Anmeldung fehlt" in lines[-1] and "GEHEIM" not in lines[-1]


# ── Stopp mitten im Review (TR3-Review B1, V1) ───────────────────────────

CHILD = r'''
import os, signal, sys
from conclave_reviewer import command, cli

pidfile, marker = sys.argv[1], sys.argv[2]

class Reviewer:                      # nur was _shutdown braucht
    claude_proc = None
    def stop_claude(self): command.kill_claude(self.claude_proc)
    def drop_worktrees(self): open(marker, "w").write("worktrees entfernt")
    def log(self, msg): print(msg, flush=True)

r = Reviewer()
cli._stop_signals(r)
claude = [sys.executable, "-c", f"import os, time; open({pidfile!r}, 'w').write(str(os.getpid())); time.sleep(120)"]
command.run_claude(claude, ".", 5, print, "api#1", on_start=lambda p: setattr(r, "claude_proc", p))
'''


def _alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace").stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def test_stop_signal_during_a_review_ends_claude_quickly(tmp_path):
    """Strg+Untbr (Windows) bzw. SIGTERM, waehrend claude laeuft und der Reviewer auf es wartet (V1)."""
    pidfile, marker = tmp_path / "claude.pid", tmp_path / "worktrees"
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(
        str(ROOT / part) for part in ("src", "packages/board/src", "packages/reviewer/src")))
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    proc = subprocess.Popen([sys.executable, "-c", CHILD, str(pidfile), str(marker)], env=env, cwd=tmp_path,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=flags)
    try:
        assert _wait(pidfile.exists, 30), proc.stderr.read() if proc.poll() is not None else "claude startete nicht"
        claude_pid = int(pidfile.read_text(encoding="utf-8"))
        time.sleep(1)                                                    # sicher beim Warten auf claude
        started = time.monotonic()
        proc.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
        assert proc.wait(30) == 0
        took = time.monotonic() - started
    finally:
        if proc.poll() is None:
            proc.kill()
    assert took < 10, f"Stopp dauerte {took:.1f} s"
    assert _wait(lambda: not _alive(claude_pid), 10), "claude laeuft noch"
    assert marker.read_text(encoding="utf-8") == "worktrees entfernt"


def test_keyboard_interrupt_while_waiting_kills_claude_first(monkeypatch):
    """Strg+C kommt beim Warten auf claude an: claude wird beendet, bevor die Ausnahme weiterlaeuft (B1)."""
    from conclave_reviewer import command
    order = []

    class Proc:
        returncode = None
        stdout = stderr = None
        args = ["claude"]

        def poll(self):
            raise KeyboardInterrupt

    monkeypatch.setattr(command, "start_claude", lambda cmd, cwd: Proc())
    monkeypatch.setattr(command, "kill_claude", lambda proc: order.append("kill"))
    with pytest.raises(KeyboardInterrupt):
        command.run_claude(["claude"], ".", 1, lambda m: None, "api#1")
    assert order == ["kill"]
