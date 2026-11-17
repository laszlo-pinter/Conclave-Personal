"""P8 (conclave#83): ``conclave board wait`` endet mit einer JSON-Zeile, wenn ein Review
entschieden ist oder der Mensch steuert; nach ``--timeout`` mit Exit-Code 2.

Der Server laeuft im Prozess (WSGI); ``sleep`` loest die Ereignisse aus, die sonst der
Watcher bzw. der Mensch ausloest, und die Uhr ist kuenstlich.
"""

import io
import json
from types import SimpleNamespace

import httpx
import pytest

pytest.importorskip("flask")

from conclave.cli import board_wait  # noqa: E402
from conclave.cli.config import ConclaveConfig  # noqa: E402

HUMAN, AGENT, REVIEWER = "cvh_mensch", "cva_agent", "cvr_reviewer"
TASKS = "/board/v1/projects/api/tasks"


def _h(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def app(tmp_path):
    from conclave.api.server import _build_app
    app, _ = _build_app(ConclaveConfig(db_path=tmp_path / "c.db", api_key=HUMAN, agent_api_key=AGENT,
                                       reviewer_api_key=REVIEWER))
    app.config["TESTING"] = True
    c = app.test_client()
    assert c.post("/board/v1/projects", json={"slug": "api", "name": "API"}, headers=_h(HUMAN)).status_code == 201
    for title in ("eins", "zwei"):
        assert c.post("/board/v1/tasks", json={"project": "api", "title": title}, headers=_h(HUMAN)).status_code == 201
    assert c.patch(f"{TASKS}/1", json={"status": "review"}, headers=_h(HUMAN)).status_code == 200
    return app


def _reader(app, token=AGENT):
    return board_wait.BoardReader("http://localhost", token,
                                  client=httpx.Client(transport=httpx.WSGITransport(app=app), base_url="http://localhost"))


class Script:
    """Kuenstliche Zeit; beim n-ten Schlafen passiert etwas auf dem Board."""

    def __init__(self, actions=None):
        self.now = 0.0
        self.calls = 0
        self.actions = actions or {}

    def sleep(self, seconds):
        self.calls += 1
        self.now += seconds
        if self.calls in self.actions:
            self.actions[self.calls]()

    def clock(self):
        return self.now


def _args(ref="", project="", timeout=60, interval=5):
    return SimpleNamespace(ref=ref, project=project, timeout=timeout, interval=interval, url="", human=False)


def _run(app, script, **kw):
    out = io.StringIO()
    code = board_wait.run(_args(**kw), reader=_reader(app), sleep=script.sleep, clock=script.clock, out=out)
    lines = out.getvalue().splitlines()
    assert len(lines) == 1
    return code, json.loads(lines[0])


def _review(app, number, state, **extra):
    resp = app.test_client().post(f"{TASKS}/{number}/review", json={"state": state, "comment": "Urteil", **extra},
                                  headers=_h(REVIEWER))
    assert resp.status_code == 200, resp.get_json()


@pytest.mark.parametrize("state, verdict", [("passed", "gruen"), ("rework", "gelb"), ("failed", "rot")])
def test_wait_for_a_ticket_ends_with_the_verdict(app, state, verdict):
    script = Script({1: lambda: _review(app, 1, "running"),
                     3: lambda: _review(app, 1, state, blocking=1, suggestions=2, checked="x @ abc1234")})
    code, result = _run(app, script, ref="api#1")
    assert code == 0
    assert {k: result[k] for k in ("event", "task", "state", "verdict", "blocking", "suggestions", "checked")} == {
        "event": "review", "task": "api#1", "state": state, "verdict": verdict, "blocking": 1, "suggestions": 2,
        "checked": "x @ abc1234"}
    assert script.calls == 3                                   # "laeuft" weckt nicht


def test_a_result_from_before_the_start_does_not_count(app):
    _review(app, 1, "rework")                                  # altes Ergebnis; Ticket geht nach todo
    client = app.test_client()
    client.patch(f"{TASKS}/1", json={"status": "review"}, headers=_h(HUMAN))
    _review(app, 1, "passed")
    script = Script({2: lambda: client.post(f"{TASKS}/1/comments", json={"body": "x"}, headers=_h(HUMAN))})
    code, result = _run(app, script, ref="api#1", timeout=1)
    assert code == 2 and result["event"] == "timeout"         # nur ein Kommentar, kein neues Ergebnis


def test_timeout_has_exit_code_two(app, capsys):
    code, result = _run(app, Script(), ref="api#1", timeout=0.5, interval=10)
    assert code == 2 and result == {"event": "timeout", "minutes": 0.5}
    assert "Zeit abgelaufen" in capsys.readouterr().err


def test_wait_for_a_project_ends_on_a_review_result(app):
    script = Script({2: lambda: _review(app, 1, "passed")})
    code, result = _run(app, script, project="api")
    assert code == 0 and (result["event"], result["task"], result["verdict"]) == ("review", "api#1", "gruen")


def test_wait_for_a_project_ends_on_a_pause(app):
    pause = lambda: app.test_client().post("/board/v1/tasks", json={  # noqa: E731
        "project": "api", "title": "Stopp", "kind": "control", "control": "pause", "scope": "project"},
        headers=_h(HUMAN))
    code, result = _run(app, Script({2: pause}), project="api")
    assert code == 0
    assert (result["event"], result["type"], result["reason"]) == ("control", "pause", "Stopp")


def test_an_existing_pause_does_not_end_the_wait(app):
    app.test_client().post("/board/v1/tasks", json={"project": "api", "title": "alt", "kind": "control",
                                                    "control": "pause", "scope": "project"}, headers=_h(HUMAN))
    code, result = _run(app, Script(), project="api", timeout=0.5)
    assert code == 2 and result["event"] == "timeout"


def test_reviewer_token_is_refused_before_sending(monkeypatch, capsys):
    monkeypatch.setenv("CONCLAVE_AGENT_KEY", REVIEWER)
    monkeypatch.setenv("CONCLAVE_API_URL", "http://127.0.0.1:9")      # wuerde gesendet: "nicht erreichbar"
    assert board_wait.run(_args(ref="api#1")) == 1
    err = capsys.readouterr().err
    assert "Reviewer-Token" in err and "erreichbar" not in err and REVIEWER not in err


def test_agent_token_is_enough_and_never_printed(app, capsys):
    code, result = _run(app, Script({1: lambda: _review(app, 1, "passed")}), ref="api#1")
    captured = capsys.readouterr()
    assert code == 0 and AGENT not in captured.out + captured.err + json.dumps(result)


def test_ref_or_project_but_not_both(capsys):
    assert board_wait.run(_args()) == 1
    assert board_wait.run(_args(ref="api#1", project="api")) == 1
    assert "Entweder" in capsys.readouterr().err


def test_unknown_ticket_is_an_error(app, capsys):
    code = board_wait.run(_args(ref="api#99"), reader=_reader(app), sleep=lambda s: None, clock=lambda: 0)
    assert code == 1 and "Nicht gefunden" in capsys.readouterr().err


def test_cli_offers_the_wait_command():
    from conclave.cli.main import build_parser
    args = build_parser().parse_args(["board", "wait", "conclave#12", "--timeout", "5"])
    assert (args.board_command, args.ref, args.timeout, args.interval) == ("wait", "conclave#12", 5.0, 5.0)
