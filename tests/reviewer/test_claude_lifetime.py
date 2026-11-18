"""W4-Review B1 (#92): claude ueberlebt den Reviewer nicht, samt seinen Kindprozessen.

Ein Fake-claude startet seinerseits einen Kindprozess (wie claude seine Werkzeuge) und schreibt
beide PIDs. Der "Reviewer" ist ein eigener Prozess, der den Fake ueber ``command.start_claude``
startet und dann endet: von aussen beendet (Windows TerminateProcess), mit ``os._exit`` (Ende mit
dem Desktop) oder mit SIGTERM (POSIX, ``stop_reviewer``).
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conclave.reviewer.status import process_alive

ROOT = Path(__file__).resolve().parents[2]

FAKE_CLAUDE = """
import json, subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
open(sys.argv[1], "w").write(json.dumps([__import__("os").getpid(), child.pid]))
time.sleep(120)
"""

REVIEWER = """
import os, signal, sys, time
from conclave.reviewer import command
proc = command.start_claude([sys.executable, "-c", sys.argv[1], sys.argv[2]], ".")
if os.name != "nt":
    signal.signal(signal.SIGTERM, lambda *_: (command.kill_claude(proc), os._exit(0)))
while not os.path.exists(sys.argv[2]):
    time.sleep(0.1)
print("ready", flush=True)
if sys.argv[3] == "exit":
    sys.stdin.readline()                                       # erst, wenn der Test es sagt
    command.kill_claude(proc) if os.name != "nt" else None   # Ende mit dem Desktop: gone() raeumt auf
    os._exit(0)
time.sleep(120)
"""


def _run(tmp_path, mode):
    pids_file = tmp_path / "pids.json"
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT / "src"), str(ROOT / "packages" / "board" / "src"),
                                                      str(ROOT / "packages" / "reviewer" / "src")]))
    reviewer = subprocess.Popen([sys.executable, "-c", REVIEWER, FAKE_CLAUDE, str(pids_file), mode],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env, cwd=tmp_path)
    assert reviewer.stdout.readline().strip() == "ready"
    pids = json.loads(pids_file.read_text())
    assert all(process_alive(p) for p in pids)
    return reviewer, pids


def _gone(pids, timeout=15.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not any(process_alive(p) for p in pids):
            return True
        time.sleep(0.2)
    return False


def _cleanup(pids):
    for p in pids:
        if process_alive(p):
            try:
                os.kill(p, 9)
            except OSError:
                pass


@pytest.mark.skipif(os.name != "nt", reason="Job-Objekt: Windows")
def test_claude_dies_when_the_reviewer_is_terminated(tmp_path):
    reviewer, pids = _run(tmp_path, "wait")
    try:
        reviewer.kill()                                  # TerminateProcess, wie stop_reviewer unter Windows
        reviewer.wait(10)
        assert _gone(pids), "claude oder sein Kindprozess lebt noch"
    finally:
        _cleanup(pids)


def test_claude_dies_when_the_reviewer_ends_with_the_desktop(tmp_path):
    reviewer, pids = _run(tmp_path, "exit")              # os._exit wie in gone()
    try:
        reviewer.stdin.write("los\n")
        reviewer.stdin.flush()
        reviewer.wait(10)
        assert _gone(pids), "claude oder sein Kindprozess lebt noch"
    finally:
        _cleanup(pids)


@pytest.mark.skipif(os.name == "nt", reason="SIGTERM: POSIX")
def test_claude_dies_on_sigterm(tmp_path):
    import signal
    reviewer, pids = _run(tmp_path, "wait")
    try:
        reviewer.send_signal(signal.SIGTERM)             # stop_reviewer unter POSIX
        reviewer.wait(10)
        assert _gone(pids)
    finally:
        _cleanup(pids)


def test_timeout_kills_the_whole_claude_tree(tmp_path):
    from conclave.reviewer import command
    pids_file = tmp_path / "pids.json"
    logs = []
    outcome = command.run_claude([sys.executable, "-c", FAKE_CLAUDE, str(pids_file)], str(tmp_path), 3 / 60,
                                 logs.append, "api#1")
    assert outcome == "timeout" and "stopped after" in logs[-1]
    pids = json.loads(pids_file.read_text())
    try:
        assert _gone(pids)
    finally:
        _cleanup(pids)
