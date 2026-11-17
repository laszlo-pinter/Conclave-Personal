"""W4 (#92): ``conclave desktop`` startet den Reviewer genau dann, wenn er konfiguriert ist, nie doppelt;
er endet mit dem Desktop. ``conclave-reviewer status`` bei laufendem und gestopptem Reviewer.

Nur mit Testkonfiguration (``CONCLAVE_CONFIG_FILE``, ``CONCLAVE_REVIEWER_DATA_DIR``); echte Kindprozesse,
der Board-Server ist absichtlich nicht erreichbar (der Reviewer wartet dann einfach).
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conclave.reviewer import status as rs
from conclave.reviewer.cli import main
from conclave.runtime import reviewer_launch as rl
from tests.reviewer.test_hardening import _hold

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def env(tmp_path, monkeypatch):
    conf = tmp_path / "conclave" / "config.toml"
    conf.parent.mkdir()
    token = tmp_path / "conclave" / "reviewer.token"
    token.write_text("cvr_test\n", encoding="utf-8")
    data = tmp_path / "rdata"
    monkeypatch.setenv("CONCLAVE_CONFIG_FILE", str(conf))
    monkeypatch.setenv("CONCLAVE_REVIEWER_DATA_DIR", str(data))
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(ROOT / "src"), str(ROOT / "packages" / "board" / "src")]))
    section = ("[reviewer]\nconclave_url = \"http://127.0.0.1:9\"\npoll_seconds = 1\nclaude_exe = \"claude\"\n"
               f"reviewer_token_file = {json.dumps(str(token))}\n[reviewer.projects]\napi = {json.dumps(str(tmp_path))}\n")
    return {"conf": conf, "token": token, "data": data, "section": section}


def _wait(predicate, timeout=30.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.2)
    return False


# ── konfiguriert? ────────────────────────────────────────────────────────

def test_not_configured_without_file_or_section(env):
    assert rl.reviewer_configured()[:2] == (False, f"keine Konfiguration unter {env['conf']}")
    env["conf"].write_text("[server]\nport = 8000\n", encoding="utf-8")
    assert rl.reviewer_configured()[1] == "kein Abschnitt [reviewer] in der Konfiguration"


def test_not_configured_when_disabled_or_without_token(env):
    env["conf"].write_text(env["section"].replace("[reviewer]\n", "[reviewer]\nenabled = false\n"), encoding="utf-8")
    assert rl.reviewer_configured()[1] == "[reviewer] enabled = false"
    env["conf"].write_text(env["section"], encoding="utf-8")
    env["token"].unlink()
    assert rl.reviewer_configured()[1].startswith("reviewer.token fehlt")


def test_configured(env):
    env["conf"].write_text(env["section"], encoding="utf-8")
    assert rl.reviewer_configured()[:2] == (True, "konfiguriert")


def test_no_start_and_a_hint_when_not_configured(env, monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("darf nicht starten"))
    logs = []
    assert rl.start_reviewer(logs.append) is None
    assert logs and logs[0].startswith("Reviewer nicht gestartet")


# ── Start, nie doppelt, Ende mit dem Desktop ─────────────────────────────

def test_starts_a_child_without_console_and_never_twice(env):
    env["conf"].write_text(env["section"], encoding="utf-8")
    logs = []
    proc = rl.start_reviewer(logs.append)
    try:
        assert proc is not None and logs[-1].startswith("Reviewer gestartet")
        assert _wait(lambda: rs.is_running(env["data"] / "reviewer.lock")), "Kind haelt die Sperre nicht"
        assert rl.start_reviewer(logs.append) is None                          # nie doppelt
        assert "laeuft schon" in logs[-1]
    finally:
        rl.stop_reviewer(proc)
    assert proc.poll() is not None
    assert _wait(lambda: not rs.is_running(env["data"] / "reviewer.lock"))


def test_no_start_next_to_the_old_watcher(env, tmp_path):
    legacy = tmp_path / "alt" / "watcher.lock"
    legacy.parent.mkdir()
    env["conf"].write_text(env["section"].replace(
        "[reviewer.projects]", f"legacy_lock_file = {json.dumps(str(legacy))}\n[reviewer.projects]"), encoding="utf-8")
    holder = _hold(legacy)
    try:
        logs = []
        assert rl.start_reviewer(logs.append) is None and "alte Watcher" in logs[-1]
    finally:
        holder.kill()
        holder.wait(10)


def test_reviewer_ends_with_its_parent(env):
    env["conf"].write_text(env["section"], encoding="utf-8")
    parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    child = subprocess.Popen([sys.executable, "-m", "conclave.reviewer", "run", "--parent-pid", str(parent.pid)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert _wait(lambda: rs.is_running(env["data"] / "reviewer.lock"))
        parent.kill()                                                          # Desktop weg (auch Absturz)
        parent.wait(10)
        child.wait(30)
        assert child.returncode == 0
        assert "beendet, Reviewer endet" in (env["data"] / "reviewer.log").read_text(encoding="utf-8")
    finally:
        for p in (child, parent):
            if p.poll() is None:
                p.kill()


def test_desktop_starts_and_stops_the_reviewer(monkeypatch, tmp_path):
    """``conclave desktop`` (``_run_server`` mit Browser) startet ihn und beendet ihn danach; ``server`` nicht."""
    from conclave.cli import main as cli_main
    calls = []
    monkeypatch.setattr("conclave.runtime.reviewer_launch.start_reviewer", lambda log: calls.append("start") or "P")
    monkeypatch.setattr("conclave.runtime.reviewer_launch.stop_reviewer", lambda proc: calls.append(("stop", proc)))
    monkeypatch.setattr("conclave.runtime.serve.serve", lambda *a, **k: calls.append("serve"))
    monkeypatch.setattr(cli_main, "open_browser", lambda url: None)
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("CONCLAVE_DB_PATH", str(tmp_path / "c.db"))
    for name in ("CONCLAVE_API_TOKEN_FILE", "CONCLAVE_AGENT_TOKEN_FILE", "CONCLAVE_REVIEWER_TOKEN_FILE",
                 "CONCLAVE_SECRET_KEY_FILE"):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))
    args = cli_main.build_parser().parse_args(["desktop", "--port", "0"])
    assert cli_main._run_server(args, should_open_browser=True) == 0
    assert calls == ["start", "serve", ("stop", "P")]
    calls.clear()
    args = cli_main.build_parser().parse_args(["server", "--port", "0"])
    assert cli_main._run_server(args, should_open_browser=False) == 0
    assert calls == ["serve"]                                                  # server startet keinen Reviewer


# ── status ───────────────────────────────────────────────────────────────

def test_status_when_stopped(env, capsys, monkeypatch):
    env["conf"].write_text(env["section"], encoding="utf-8")
    env["data"].mkdir()
    (env["data"] / "status.json").write_text(json.dumps({
        "pid": 1, "current_task": "api#7", "last_result": {"task": "api#7", "outcome": "done", "at": "2026-11-17T20:00:00"}}),
        encoding="utf-8")
    (env["data"] / "state.json").write_text(json.dumps({"statuses": {}, "pending": [],
                                                        "reviews": [time.time() - 60, time.time() - 7200]}),
                                            encoding="utf-8")
    monkeypatch.setattr(rs, "claude_version", lambda cfg: ("2.1.326", None))
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "Reviewer laeuft: nein" in out and "Laufendes Ticket" not in out        # gestoppt: kein laufendes Ticket
    assert "Letztes Ergebnis: api#7 done" in out and "Reviews in der letzten Stunde: 1" in out
    assert "claude: 2.1.326" in out and "WARNUNG" not in out


def test_status_while_running(env, capsys, monkeypatch):
    env["conf"].write_text(env["section"], encoding="utf-8")
    monkeypatch.setattr(rs, "claude_version", lambda cfg: ("3.0.0", "unbekannte Version von claude (3.0.0)"))
    proc = rl.start_reviewer(lambda msg: None)
    try:
        assert _wait(lambda: (env["data"] / "status.json").exists() and rs.is_running(env["data"] / "reviewer.lock"))
        assert main(["status", "--json"]) == 0
        info = json.loads(capsys.readouterr().out)
        assert info["running"] is True and info["pid"] == proc.pid and info["current_task"] is None
        assert info["claude_warning"].startswith("unbekannte Version")
    finally:
        rl.stop_reviewer(proc)


def test_claude_version_warns_on_another_major(tmp_path):
    version, warning = rs.claude_version({"claude_exe": sys.executable})          # "Python 3.x" statt claude 2.x
    assert version and version.startswith("3.") and "unbekannte Version" in warning
    assert rs.claude_version({"claude_exe": str(tmp_path / "fehlt.exe")})[1].startswith("claude nicht gefunden")
