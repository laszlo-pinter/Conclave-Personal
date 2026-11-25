"""conclave#158: gemeinsame Warte-Logik im Kern (``conclave_board.wait``), ohne HTTP, mit einem Lese-Ersatz.

Der Fall mit Konten (Team): gleiche Herkunft, andere Person weckt; gleiche Herkunft und Person nicht.
"""

import pytest

from conclave_board.wait import Waiter, WaitError


class Board:
    def __init__(self, me):
        self.me, self.changes, self.comments, self.fail = me, 0, [], 0

    def add(self, cid, origin, actor_id, name=None):
        self.comments.append({"id": cid, "origin": origin, "actor_id": actor_id, "actor_name": name, "body": "TEXT"})
        self.changes += 1

    def get(self, path, params=None):
        if path == "/auth/whoami":
            return self.me
        if path == "/board/v1/changes":
            if self.fail:
                self.fail -= 1
                raise ConnectionError("kurz weg")
            return {"changes": self.changes}
        assert path == "/board/v1/projects/api/tasks/3"
        return {"ref": "api#3", "title": "Chat", "status": "done", "comments": list(self.comments)}


def _waiter(board, actions, timeout=60):
    state = {"calls": 0, "now": 0.0}

    def sleep(s):
        state["calls"] += 1
        state["now"] += s
        actions.get(state["calls"], lambda: None)()

    return Waiter(board, interval=5, timeout=timeout, sleep=sleep, clock=lambda: state["now"],
                  transient=(ConnectionError,)), state


def test_same_origin_other_person_wakes_the_agent():
    board = Board({"role": "agent", "actor_id": "u_anna"})
    board.add("c0", "human", "u_anna", "Anna")                       # vor dem Start
    waiter, state = _waiter(board, {1: lambda: board.add("c1", "agent", "u_anna", "Anna"),   # eigener Zugang
                                    2: lambda: board.add("c2", "human", "u_anna", "Anna"),   # eigener Mensch
                                    })
    result = waiter.wait_comments("api#3")
    assert (result["comment"], result["from"], result["person"]) == ("c2", "Kommentar von: Mensch Anna", "Anna")
    assert "TEXT" not in str(result) and state["calls"] == 2


def test_agent_of_another_person_wakes():
    board = Board({"role": "agent", "actor_id": "u_anna"})
    waiter, _ = _waiter(board, {1: lambda: board.add("c1", "agent", "u_ben", "Ben")})
    assert waiter.wait_comments("api#3")["from"] == "Kommentar von: Agent von Ben"


def test_without_actor_id_the_role_is_the_person():
    """Personal: whoami nennt nur die Rolle, Kommentare tragen sie als actor_id."""
    board = Board({"role": "agent"})
    waiter, state = _waiter(board, {1: lambda: board.add("c1", "agent", "agent"),
                                    2: lambda: board.add("c2", "human", "human")})
    assert waiter.wait_comments("api#3")["comment"] == "c2" and state["calls"] == 2


def test_network_errors_are_retried_and_timeout_ends():
    board = Board({"role": "human", "actor_id": "u_anna"})
    board.fail = 2
    waiter, _ = _waiter(board, {}, timeout=30)
    board.fail = 0
    waiter_fail, _ = _waiter(board, {1: lambda: setattr(board, "fail", 1),
                                     3: lambda: board.add("c1", "agent", "u_ben", "Ben")})
    assert waiter_fail.wait_comments("api#3")["comment"] == "c1"
    assert waiter.wait_comments("api#3") == {"event": "timeout", "minutes": 0.5}


def test_whoami_without_role_is_an_error():
    waiter, _ = _waiter(Board({}), {})
    with pytest.raises(WaitError, match="Rolle"):
        waiter.wait_comments("api#3")
