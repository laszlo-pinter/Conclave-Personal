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
