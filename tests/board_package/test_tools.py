"""T8: gemeinsame Board-Tools (``conclave_board.tools``) und Erweiterungspunkt ``BoardPolicy.actor_name``,
ohne Team-Code und ohne MCP.

- Texte anderer tragen Herkunft und Person (``from``), der Anzeigename bleibt als solcher markiert
- die Tools laufen gegen die Board-App des Kerns ueber einen beliebigen Transport
- ``actor_name`` erscheint an Ticket, Kommentaren und Verlauf; ohne Erweiterung ist es null (Personal)
"""

import pytest

from conclave_board.api.app import create_board_app
from conclave_board.application.policy import PersonalPolicy
from conclave_board.infrastructure.auth import StaticKeyAuthService
from conclave_board.server import open_board
from conclave_board.tools import BOARD_DATA_NOTE, BoardTools, who

HUMAN, AGENT, REVIEWER = "cvh_mensch", "cva_agent", "cvr_reviewer"


class Named(PersonalPolicy):
    NAMES = {"human": "Laszlo", "agent": "Laszlo", "reviewer": "Bot"}

    def actor_name(self, actor_id):
        return self.NAMES.get(actor_id)


@pytest.fixture
def setup(tmp_path):
    board, _conn = open_board(db_path=tmp_path / "board.db", config_dir=tmp_path / "config")
    app = create_board_app(board, StaticKeyAuthService(HUMAN, AGENT, REVIEWER))
    client = app.test_client()
    client.post("/board/v1/projects", json={"slug": "api", "name": "API"}, headers=_h(HUMAN))
    return board, client


def _h(token):
    return {"Authorization": f"Bearer {token}"}


class Failure(Exception):
    pass


def _tools(client, token):
    def request(method, path, params=None, json=None):
        r = client.open(path, method=method, query_string=params, json=json, headers=_h(token))
        if r.status_code >= 400:
            raise Failure(f"{r.status_code}: {(r.get_json() or {}).get('error')}")
        return r.get_json() or {}
    return BoardTools(request, Failure)


def test_who_names_origin_and_person():
    assert who("agent", "u_1", "Anna") == "Agent von Anna"
    assert who("human", "u_1", "Anna") == "Mensch Anna"
    assert who("reviewer", "u_2", "Bot") == "Reviewer Bot"
    assert who("agent", "agent", None) == "Agent"                                   # Personal: nur die Rolle
    assert who("system", "conclave", "x") == "Conclave"
    assert who(None) == "unbekannt (importiert)"


def test_tools_label_texts_of_others_in_personal(setup):
    _board, client = setup
    agent = _tools(client, AGENT)
    created = agent.create("api", "T", description="Text")
    assert created["task"] == "api#1"
    agent.next(task="api#1")
    agent.add_comment("api#1", "Commit abc", author="cc")
    detail = agent.get("api#1")
    assert detail["note"] == BOARD_DATA_NOTE and "Links" in detail["note"]
    assert detail["description_from"] == "Beschreibung von: Agent"
    assert detail["comments"] == [{"from": "Kommentar von: Agent", "origin": "agent", "person": "agent",
                                   "author": "cc", "body": "Commit abc"}]
    assert [h["by"] for h in detail["history"]] == ["Agent", "Agent"]


def test_actor_name_extension_point_in_the_api(setup):
    board, client = setup
    client.post("/board/v1/tasks", json={"project": "api", "title": "T"}, headers=_h(HUMAN))
    client.post("/board/v1/projects/api/tasks/1/comments", json={"body": "x"}, headers=_h(AGENT))
    plain = client.get("/board/v1/projects/api/tasks/1", headers=_h(HUMAN)).get_json()
    assert plain["actor_name"] is None and plain["comments"][0]["actor_name"] is None   # Personal: null
    board.policy = Named()
    named = client.get("/board/v1/projects/api/tasks/1", headers=_h(HUMAN)).get_json()
    assert named["actor_name"] == "Laszlo" and named["comments"][0]["actor_name"] == "Laszlo"
    history = client.get("/board/v1/projects/api/tasks/1/history", headers=_h(HUMAN)).get_json()["history"]
    assert {h["actor_name"] for h in history} == {"Laszlo"}
    agent = _tools(client, AGENT).get("api#1")
    assert agent["comments"][0]["from"] == "Kommentar von: Agent von Laszlo"
    assert agent["description_from"] == "Beschreibung von: Mensch Laszlo"


def test_names_are_asked_once_per_request(setup):
    board, client = setup
    client.post("/board/v1/tasks", json={"project": "api", "title": "T"}, headers=_h(HUMAN))
    for i in range(5):
        client.post("/board/v1/projects/api/tasks/1/comments", json={"body": f"x{i}"}, headers=_h(AGENT))
    asked = []

    class Counting(Named):
        def actor_name(self, actor_id):
            asked.append(actor_id)
            return super().actor_name(actor_id)

    board.policy = Counting()
    client.get("/board/v1/projects/api/tasks/1", headers=_h(HUMAN))
    assert sorted(asked) == ["agent", "human"]


def test_tools_reject_bad_references_and_empty_updates(setup):
    _board, client = setup
    tools = _tools(client, AGENT)
    for bad in ("api#x", "../etc", ""):
        with pytest.raises(Failure):
            tools.get(bad)
    with pytest.raises(Failure, match="Ungueltige ID"):
        tools.seg("a/b")
    with pytest.raises(Failure, match="Nichts zu aendern"):
        tools.update("api#1")


def test_title_and_description_name_who_wrote_them_last(setup):
    """#76-Review B1: nicht der Ersteller, sondern wer Titel bzw. Beschreibung zuletzt geschrieben hat."""
    board, client = setup
    client.post("/board/v1/tasks", json={"project": "api", "title": "T", "description": "vom Menschen"},
                headers=_h(HUMAN))
    board.policy = Named()
    agent = _tools(client, AGENT)
    fresh = agent.get("api#1")
    assert (fresh["title_from"], fresh["description_from"]) == ("Titel von: Mensch Laszlo",
                                                                "Beschreibung von: Mensch Laszlo")
    agent.update("api#1", description="vom Agenten")
    changed = agent.get("api#1")
    assert changed["description_from"] == "Beschreibung von: Agent von Laszlo"
    assert changed["title_from"] == "Titel von: Mensch Laszlo"                     # Titel unveraendert
    agent.update("api#1", title="neu")
    taken = agent.next(task="api#1")                                              # auch in next
    assert taken["title_from"] == "Titel von: Agent von Laszlo"
    assert taken["description_from"] == "Beschreibung von: Agent von Laszlo"
