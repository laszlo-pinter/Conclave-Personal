# tests/api/test_auto_loop.py
#
# Tests für auto_loop:
#   Teil 1: CLIHandler.auto_loop() direkt (Generator-Logik)
#   Teil 2: POST /conversations/<id>/auto-loop Endpoint (Format & Validierung)

import json
import pytest

pytest.importorskip("flask")

from unittest.mock import MagicMock
from conclave.api.app import create_app
from conclave.cli.handler import CLIHandler, CLIResult


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_ok(pid: str, content: str, seq: int = 1) -> CLIResult:
    return CLIResult(
        success=True,
        message=f"Antwort von '{pid}'.",
        data={"participant_id": pid, "content": content, "sequence": seq},
    )


def run_loop(mock_handler, conversation_id, sequence, stop_signal="@done", max_rounds=20):
    """Ruft CLIHandler.auto_loop() direkt auf und gibt alle Events als Liste zurück."""
    return list(CLIHandler.auto_loop(
        mock_handler, conversation_id, sequence, stop_signal, max_rounds
    ))


def make_mock_handler(**kwargs):
    h = MagicMock()
    if "invoke_side_effect" in kwargs:
        h.invoke_participant.side_effect = kwargs["invoke_side_effect"]
    elif "invoke_return" in kwargs:
        h.invoke_participant.return_value = kwargs["invoke_return"]
    return h


# ── Fixtures für Endpoint-Tests ───────────────────────────────────────────────

@pytest.fixture
def handler():
    h = MagicMock()
    h.list_conversations.return_value = CLIResult(
        success=True, message="ok", data={"conversations": []}
    )
    return h


@pytest.fixture
def client(handler):
    app = create_app(handler)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ── Teil 1: Handler-Generator-Logik ──────────────────────────────────────────

class TestAutoLoopHandlerLogic:

    def test_start_event_is_first(self):
        h = make_mock_handler(invoke_side_effect=[make_ok("cc", "Hallo @done")])
        events = run_loop(h, "conv-1", ["cc", "cd"], "@done", max_rounds=5)
        assert events[0]["event"] == "start"
        assert events[0]["sequence"] == ["cc", "cd"]
        assert events[0]["stop_signal"] == "@done"
        assert events[0]["max_rounds"] == 5

    def test_invoke_event_per_participant(self):
        h = make_mock_handler(invoke_side_effect=[
            make_ok("cc", "weiter"),
            make_ok("cd", "fertig @done"),
        ])
        events = run_loop(h, "conv-1", ["cc", "cd"])
        invoke_events = [e for e in events if e["event"] == "invoke"]
        assert len(invoke_events) == 2
        assert invoke_events[0]["participant"] == "cc"
        assert invoke_events[1]["participant"] == "cd"

    def test_response_event_contains_content(self):
        h = make_mock_handler(invoke_side_effect=[make_ok("cc", "Meine Antwort @done")])
        events = run_loop(h, "conv-1", ["cc"])
        resp_events = [e for e in events if e["event"] == "response"]
        assert resp_events[0]["content"] == "Meine Antwort @done"

    def test_participants_invoked_in_order(self):
        h = make_mock_handler(invoke_side_effect=[
            make_ok("cc", "cc-antwort"),
            make_ok("cd", "cd-antwort @done"),
        ])
        run_loop(h, "conv-1", ["cc", "cd"])
        calls = h.invoke_participant.call_args_list
        assert calls[0].args == ("conv-1", "cc")
        assert calls[1].args == ("conv-1", "cd")

    def test_stops_after_first_participant_with_signal(self):
        h = make_mock_handler(invoke_side_effect=[
            make_ok("cc", "Fertig. @done"),
            make_ok("cd", "wird nicht aufgerufen"),
        ])
        events = run_loop(h, "conv-1", ["cc", "cd"])
        assert h.invoke_participant.call_count == 1
        stop = next(e for e in events if e["event"] == "stop")
        assert stop["reason"] == "signal"
        assert stop["participant"] == "cc"
        assert stop["signal"] == "@done"

    def test_stops_after_second_participant_with_signal(self):
        h = make_mock_handler(invoke_side_effect=[
            make_ok("cc", "Ich mache weiter"),
            make_ok("cd", "Ich bin fertig @done"),
        ])
        events = run_loop(h, "conv-1", ["cc", "cd"])
        assert h.invoke_participant.call_count == 2
        stop = next(e for e in events if e["event"] == "stop")
        assert stop["participant"] == "cd"
        assert stop["round"] == 1

    def test_stops_at_max_rounds(self):
        h = make_mock_handler(invoke_return=make_ok("cc", "keine Fertigmeldung"))
        events = run_loop(h, "conv-1", ["cc"], max_rounds=3)
        assert h.invoke_participant.call_count == 3
        stop = next(e for e in events if e["event"] == "stop")
        assert stop["reason"] == "max_rounds"
        assert stop["rounds"] == 3

    def test_default_max_rounds_is_capped(self):
        h = make_mock_handler(invoke_return=make_ok("cc", "weiter"))
        events = run_loop(h, "conv-1", ["cc"])  # default max_rounds
        stop = next(e for e in events if e["event"] == "stop")
        assert stop["reason"] == "max_rounds"
        assert stop["rounds"] <= 50

    def test_stop_signal_case_insensitive(self):
        h = make_mock_handler(invoke_side_effect=[make_ok("cc", "Fertig. @DONE")])
        events = run_loop(h, "conv-1", ["cc"], stop_signal="@done")
        stop = next(e for e in events if e["event"] == "stop")
        assert stop["reason"] == "signal"

    def test_custom_stop_signal(self):
        h = make_mock_handler(invoke_side_effect=[make_ok("cc", "Status: FERTIG_MIT_ANALYSE")])
        events = run_loop(h, "conv-1", ["cc"], stop_signal="FERTIG_MIT_ANALYSE")
        stop = next(e for e in events if e["event"] == "stop")
        assert stop["reason"] == "signal"

    def test_invoke_failure_stops_with_error(self):
        h = make_mock_handler(invoke_return=CLIResult(
            success=False, message="Kein Adapter.", data={}
        ))
        events = run_loop(h, "conv-1", ["cc"])
        stop = next(e for e in events if e["event"] == "stop")
        assert stop["reason"] == "error"
        assert "cc" in stop["participant"]

    def test_round_counter_increments(self):
        h = make_mock_handler(invoke_side_effect=[
            make_ok("cc", "Runde 1"),
            make_ok("cc", "Runde 2"),
            make_ok("cc", "Runde 3 @done"),
        ])
        events = run_loop(h, "conv-1", ["cc"])
        invoke_events = [e for e in events if e["event"] == "invoke"]
        assert [e["round"] for e in invoke_events] == [1, 2, 3]

    def test_multi_round_sequence(self):
        """Zwei Participants, Signal erst in Runde 2 beim zweiten Participant."""
        h = make_mock_handler(invoke_side_effect=[
            make_ok("cc", "Runde 1 cc"),
            make_ok("cd", "Runde 1 cd"),
            make_ok("cc", "Runde 2 cc @done"),
        ])
        events = run_loop(h, "conv-1", ["cc", "cd"])
        assert h.invoke_participant.call_count == 3
        stop = next(e for e in events if e["event"] == "stop")
        assert stop["round"] == 2
        assert stop["participant"] == "cc"


# ── Teil 2: Endpoint — Validierung ───────────────────────────────────────────

class TestAutoLoopEndpointValidation:

    def test_missing_sequence_returns_400(self, client):
        resp = client.post("/conversations/conv-1/auto-loop", json={})
        assert resp.status_code == 400

    def test_empty_sequence_returns_400(self, client):
        resp = client.post("/conversations/conv-1/auto-loop",
                           json={"sequence": []})
        assert resp.status_code == 400

    def test_non_list_sequence_returns_400(self, client):
        resp = client.post("/conversations/conv-1/auto-loop",
                           json={"sequence": "cc"})
        assert resp.status_code == 400


# ── Teil 2: Endpoint — SSE-Format ────────────────────────────────────────────

class TestAutoLoopEndpointFormat:

    def test_response_is_event_stream(self, client, handler):
        """Content-Type muss text/event-stream sein."""
        handler.auto_loop.return_value = iter([
            {"event": "start", "rounds": 1, "sequence": ["cc"], "stop_signal": "@done"},
            {"event": "stop",  "reason": "max_rounds", "rounds": 1},
        ])
        resp = client.post("/conversations/conv-1/auto-loop", json={
            "sequence": ["cc"], "stop_signal": "@done", "max_rounds": 1,
        })
        assert "text/event-stream" in resp.content_type

    def test_response_ends_with_done(self, client, handler):
        """Letztes Event im Stream muss [DONE] sein."""
        handler.auto_loop.return_value = iter([
            {"event": "stop", "reason": "max_rounds", "rounds": 1},
        ])
        resp = client.post("/conversations/conv-1/auto-loop", json={
            "sequence": ["cc"], "max_rounds": 1,
        })
        assert b"[DONE]" in resp.data

    def test_handler_auto_loop_called_with_correct_args(self, client, handler):
        """Endpoint muss handler.auto_loop() mit den richtigen Argumenten aufrufen."""
        handler.auto_loop.return_value = iter([
            {"event": "stop", "reason": "max_rounds", "rounds": 5},
        ])
        client.post("/conversations/conv-1/auto-loop", json={
            "sequence": ["cc", "cd"],
            "stop_signal": "@fertig",
            "max_rounds": 5,
        })
        handler.auto_loop.assert_called_once_with(
            conversation_id="conv-1",
            sequence=["cc", "cd"],
            stop_signal="@fertig",
            max_rounds=5,
        )
