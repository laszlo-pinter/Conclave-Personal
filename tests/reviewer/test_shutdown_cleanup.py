"""#98-Review (W4-Code): Startfehler brechen den Desktop nicht ab (V1), das Ende des Desktops wird
ueber ein Handle erkannt (V2), Worktrees eines abgebrochenen Reviews bleiben nicht liegen (V3).
"""

import subprocess
import sys
import threading

import pytest

pytest.importorskip("flask")

from conclave.reviewer import status as rs  # noqa: E402
from conclave.reviewer import worktrees  # noqa: E402
from conclave.runtime import reviewer_launch as rl  # noqa: E402
from tests.reviewer.test_launch import env  # noqa: E402,F401 - Fixture
from tests.reviewer.test_watch import (  # noqa: E402,F401 - Fixtures
    _claude, _ticket_in_review, cfg, repo, rv, server,
)


def _worktree_list(path) -> str:
    return subprocess.run(["git", "-C", str(path), "worktree", "list"], capture_output=True, text=True,
                          check=True).stdout


# ── V1 ───────────────────────────────────────────────────────────────────

def test_a_failing_start_is_only_logged(env, monkeypatch):
    env["conf"].write_text(env["section"], encoding="utf-8")

    def broken(*a, **k):
        raise OSError("kein Prozess")

    monkeypatch.setattr(subprocess, "Popen", broken)
    logs = []
    assert rl.start_reviewer(logs.append) is None
    assert logs[-1] == "Reviewer nicht gestartet: OSError: kein Prozess"


def test_an_unreadable_lock_is_only_logged(env, monkeypatch):
    env["conf"].write_text(env["section"], encoding="utf-8")
    monkeypatch.setattr(rl, "already_running", lambda cfg: (_ for _ in ()).throw(PermissionError("gesperrt")))
    logs = []
    assert rl.start_reviewer(logs.append) is None and "PermissionError: gesperrt" in logs[-1]


# ── V2 ───────────────────────────────────────────────────────────────────

def _watch(pid) -> threading.Event:
    gone = threading.Event()
    rs.watch_parent(pid, gone.set, every=0.1)
    return gone


def test_parent_exit_is_seen():
    parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        gone = _watch(parent.pid)
        assert not gone.wait(1.0)
        parent.kill()
        parent.wait(10)
        assert gone.wait(10)
    finally:
        if parent.poll() is None:
            parent.kill()


def test_a_parent_that_is_already_gone_counts_as_gone():
    done = subprocess.Popen([sys.executable, "-c", "pass"])
    done.wait(10)
    assert _watch(done.pid).wait(10)


# ── V3 ───────────────────────────────────────────────────────────────────

def test_exit_during_a_review_removes_its_worktrees(rv, server, repo, monkeypatch):
    path, head = repo
    task = _ticket_in_review(server, head)
    seen = {}

    def fake(cfg_, key, cmd, cwd):                     # wie gone(): mitten im Review
        seen["cwd"] = cwd
        rv.drop_worktrees()
        seen["after"] = (rv.worktrees / "api-1").exists()
        return "done"

    _claude(monkeypatch, rv, fake)
    rv.run_review(task, "api#1", str(path), dry_run=False)
    assert seen["cwd"].endswith("api-1") and seen["after"] is False
    assert "api-1" not in _worktree_list(path)


def test_leftover_worktrees_are_removed_at_start(rv, repo):
    path, head = repo
    left = worktrees.add_worktree(rv.worktrees, str(path), "api#7", head)   # Absturz: liegen geblieben
    assert left.exists() and "api-7" in _worktree_list(path)
    rv.clean_orphans()
    assert not left.exists() and "api-7" not in _worktree_list(path)
    assert "removed leftover worktrees: api-7" in rv.log_file.read_text(encoding="utf-8")
    rv.clean_orphans()                                  # nichts mehr da: kein Fehler, keine Zeile
    assert rv.log_file.read_text(encoding="utf-8").count("removed leftover") == 1
