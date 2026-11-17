"""W3 (#91): Herzschlag des Reviewers und Freigabe haengender Reviews (``running`` -> ``none``).

- ``POST /board/v1/reviewer/heartbeat`` nur mit dem Reviewer-Token; Agent und Mensch bekommen 403.
- ``GET /board/v1/reviewer`` und das Feld ``reviewer`` der Uebersicht: ``active`` oder ``off`` seit wann.
- ``state: none`` nur aus ``running`` und nur durch den Reviewer; kein Ergebnis, kein Rot-Zaehler.
"""

from datetime import UTC, datetime, timedelta

import pytest

from conclave_board.api.app import create_board_app
from conclave_board.infrastructure.auth import StaticKeyAuthService
from conclave_board.server import open_board

HUMAN, AGENT, REVIEWER = "cvh_mensch", "cva_agent", "cvr_reviewer"
V1 = "/board/v1"


def _h(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def env(tmp_path):
    board, _conn = open_board(db_path=tmp_path / "board.db", config_dir=tmp_path / "config")
    clock = {"now": datetime(2026, 11, 17, 12, 0, tzinfo=UTC)}
    board._now = lambda: clock["now"]
    client = create_board_app(board, StaticKeyAuthService(HUMAN, AGENT, REVIEWER)).test_client()
    client.post(f"{V1}/projects", json={"slug": "api", "name": "API"}, headers=_h(HUMAN))
    client.post(f"{V1}/tasks", json={"project": "api", "title": "T"}, headers=_h(HUMAN))
    client.patch(f"{V1}/projects/api/tasks/1", json={"status": "review"}, headers=_h(HUMAN))
    return client, clock


def _status(client):
    return client.get(f"{V1}/reviewer", headers=_h(HUMAN)).get_json()


# ── Herzschlag ───────────────────────────────────────────────────────────

def test_without_heartbeat_the_reviewer_is_off(env):
    client, _ = env
    assert _status(client) == {"state": "off", "since": None}
    assert client.get(V1, headers=_h(HUMAN)).get_json()["reviewer"]["state"] == "off"


def test_heartbeat_makes_it_active_and_silence_turns_it_off(env):
    client, clock = env
    beat = client.post(f"{V1}/reviewer/heartbeat", json={"version": "0.8.0", "task": "api#1"}, headers=_h(REVIEWER))
    assert beat.status_code == 200 and beat.get_json()["state"] == "active"
    status = _status(client)
    assert (status["state"], status["version"], status["task"]) == ("active", "0.8.0", "api#1")
    clock["now"] += timedelta(seconds=170)
    assert _status(client)["state"] == "active"                       # zwei verpasste Herzschlaege: noch aktiv
    clock["now"] += timedelta(seconds=20)
    assert _status(client) == {"state": "off", "since": "2026-11-17T12:00:00+00:00"}


@pytest.mark.parametrize("token", [AGENT, HUMAN])
def test_only_the_reviewer_may_send_a_heartbeat(env, token):
    client, _ = env
    resp = client.post(f"{V1}/reviewer/heartbeat", json={"version": "x"}, headers=_h(token))
    assert resp.status_code == 403
    assert _status(client)["state"] == "off"


def test_heartbeat_rejects_unknown_fields_and_bad_values(env):
    client, _ = env
    for body in ({"version": "x", "extra": 1}, {"version": "x" * 51}, {"task": 5}):
        assert client.post(f"{V1}/reviewer/heartbeat", json=body, headers=_h(REVIEWER)).status_code == 400


def test_reviewer_status_is_for_humans(env):
    client, _ = env
    assert client.get(f"{V1}/reviewer", headers=_h(AGENT)).status_code == 403


# ── Haengendes Review freigeben ──────────────────────────────────────────

def _review(client, state, token=REVIEWER, **extra):
    return client.post(f"{V1}/projects/api/tasks/1/review", json={"state": state, **extra}, headers=_h(token))


def test_reviewer_releases_a_hanging_review(env):
    client, _ = env
    assert _review(client, "running").status_code == 200
    released = _review(client, "none", comment="Lauf ohne Ergebnis, wird neu geprueft.")
    assert released.status_code == 200
    task = released.get_json()
    assert (task["status"], task["review"]["state"], task["review"]["at"], task["review"]["red_count"]) == (
        "review", "none", None, 0)
    history = client.get(f"{V1}/projects/api/tasks/1/history", headers=_h(HUMAN)).get_json()["history"]
    assert [(e["old"], e["new"]) for e in history if e["field"] == "review_state"][-1] == ("running", "none")
    assert client.get(f"{V1}/projects/api/tasks/1", headers=_h(HUMAN)).get_json()["comments"][-1]["origin"] == "reviewer"


def test_none_only_from_running(env):
    client, _ = env
    assert _review(client, "none").status_code == 409                # noch kein Review
    _review(client, "running")
    _review(client, "passed", comment="gruen")
    resp = _review(client, "none")
    assert resp.status_code == 409 and resp.get_json()["type"] == "ReviewNotRunning"


@pytest.mark.parametrize("token", [AGENT, HUMAN])
def test_only_the_reviewer_releases(env, token):
    client, _ = env
    _review(client, "running")
    assert _review(client, "none", token=token).status_code == 403
