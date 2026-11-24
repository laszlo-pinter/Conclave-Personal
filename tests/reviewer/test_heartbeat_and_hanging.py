"""W3 (#91): Reviewer mit Aenderungszaehler, Herzschlag und Freigabe haengender Reviews.

Gegen einen echten Conclave-Server; claude ist durch einen Stub ersetzt.
"""

import pytest

pytest.importorskip("flask")

from tests.reviewer.test_watch import (  # noqa: E402,F401 - Fixtures
    HUMAN, REVIEWER, _claude, _req, _task, _ticket_in_review, cfg, repo, rv, server,
)


def _reviewer_status(server):
    return _req(f"{server}/board/v1/reviewer", HUMAN)


def test_start_sends_a_heartbeat(rv, server):
    assert _reviewer_status(server)["state"] == "off"
    rv.loop(once=True)
    status = _reviewer_status(server)
    assert status["state"] == "active" and status["task"] is None and status["version"]


def test_heartbeat_names_the_ticket_under_review(rv, server, repo, monkeypatch):
    path, head = repo
    task = _ticket_in_review(server, head)
    seen = {}

    def fake(cfg_, key, cmd, cwd):
        rv.send_heartbeat()                                    # wie der Thread waehrend des Laufs
        seen["status"] = _reviewer_status(server)
        return "done"

    _claude(monkeypatch, rv, fake)
    rv.run_review(task, "api#1", str(path), dry_run=False)
    assert seen["status"]["task"] == "api#1" and rv.current_task is None


def test_hanging_review_is_released_commented_and_reviewed_again(rv, server, repo, monkeypatch):
    path, head = repo
    _ticket_in_review(server, head)
    _req(f"{server}/board/v1/projects/api/tasks/1/review", REVIEWER, "POST", {"state": "running"})  # Absturz
    rv.save_state({"statuses": {"api#1": "review"}, "pending": [], "reviews": []})     # schon gesehen
    reviewed = []
    _claude(monkeypatch, rv, lambda c, key, cmd, cwd: reviewed.append(key) or "done")
    rv.loop(once=True)
    assert reviewed == ["api#1"]                                                       # neu geprueft
    detail = _task(server)
    assert any("Review hing" in c["body"] and c["origin"] == "reviewer" for c in detail["comments"])
    history = _req(f"{server}/board/v1/projects/api/tasks/1/history", HUMAN)["history"]
    assert ("running", "none") in [(e["old"], e["new"]) for e in history if e["field"] == "review_state"]


def test_hanging_review_on_the_very_first_run_is_reviewed_too(rv, server, repo, monkeypatch):
    path, head = repo
    _ticket_in_review(server, head)
    _req(f"{server}/board/v1/projects/api/tasks/1/review", REVIEWER, "POST", {"state": "running"})
    reviewed = []
    _claude(monkeypatch, rv, lambda c, key, cmd, cwd: reviewed.append(key) or "done")
    rv.loop(once=True)
    assert reviewed == ["api#1"]


def test_dry_run_does_not_release(rv, server, repo):
    path, head = repo
    _ticket_in_review(server, head)
    _req(f"{server}/board/v1/projects/api/tasks/1/review", REVIEWER, "POST", {"state": "running"})
    rv.loop(once=True, dry_run=True)
    assert _task(server)["review"]["state"] == "running"
    assert "would release the hanging review" in rv.log_file.read_text(encoding="utf-8")


def test_column_is_read_only_after_a_change(rv, server, repo, monkeypatch):
    path, head = repo
    reads = []
    original = rv.fetch_tasks
    monkeypatch.setattr(rv, "fetch_tasks", lambda: reads.append(1) or original())
    state = rv.poll_once(None, dry_run=False)                 # erster Lauf: liest
    state = rv.poll_once(state, dry_run=False)
    state = rv.poll_once(state, dry_run=False)                # nichts geaendert: liest nicht
    assert len(reads) == 1
    _claude(monkeypatch, rv, lambda *a: "done")
    _ticket_in_review(server, head)                           # Aenderung: liest wieder
    rv.poll_once(state, dry_run=False)
    assert len(reads) == 2


def test_status_is_cleared_even_when_claude_does_not_start(rv, server, repo, monkeypatch):
    """#92-Review V1: kein dauerhaft falsches "laufendes Ticket", wenn claude gar nicht startet."""
    import json as _json
    path, head = repo
    task = _ticket_in_review(server, head)

    def broken(key, cmd, cwd, ask=None):
        raise OSError("claude fehlt")

    monkeypatch.setattr(rv, "run_claude", broken)
    with pytest.raises(OSError):
        rv.run_review(task, "api#1", str(path), dry_run=False)
    status = _json.loads(rv.status_file.read_text(encoding="utf-8"))
    assert status["current_task"] is None and status["last_result"]["outcome"] == "failed"
