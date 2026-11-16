"""P6 (conclave#61): Steuertickets ueber API und MCP.

Abnahme: Agent legt ein Steuerticket an oder schliesst es -> 403; offene Pause -> next liefert
paused; comment an einem Arbeitsticket zeigt die Pause im Feld control; quittierter Hinweis
steht an der Karte, unquittiert bleibt er in control; ein normales Ticket mit Pause-Text
loest nichts aus.
"""

import threading

import pytest

pytest.importorskip("flask")

from conclave.cli.config import ConclaveConfig  # noqa: E402

HUMAN, AGENT, REVIEWER = "cvh_mensch", "cva_agent", "cvr_reviewer"
URL = "/board/projects/api/tasks"


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def app(tmp_path):
    from conclave.api.server import _build_app
    app, _ = _build_app(ConclaveConfig(db_path=tmp_path / "c.db", api_key=HUMAN, agent_api_key=AGENT,
                                       reviewer_api_key=REVIEWER))
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    c = app.test_client()
    assert c.post("/board/projects", json={"slug": "api", "name": "API"}, headers=_bearer(HUMAN)).status_code == 201
    assert c.post("/board/tasks", json={"project": "api", "title": "Arbeit"}, headers=_bearer(HUMAN)).status_code == 201
    return c


def _control(client, **body):
    return client.post("/board/tasks", json={"project": "api", "kind": "control", **body}, headers=_bearer(HUMAN))


def test_agent_cannot_create_or_close_a_control_ticket(client):
    resp = client.post("/board/tasks", json={"project": "api", "title": "Pause", "kind": "control",
                                             "control": "pause"}, headers=_bearer(AGENT))
    assert resp.status_code == 403
    assert _control(client, title="Pause", control="pause", scope="all").status_code == 201
    assert client.patch(f"{URL}/2", json={"status": "done"}, headers=_bearer(AGENT)).status_code == 403
    assert client.post("/board/next", json={"task": "api#2"}, headers=_bearer(AGENT)).status_code == 403
    assert client.get(f"{URL}/2", headers=_bearer(HUMAN)).get_json()["status"] == "todo"


def test_open_pause_returns_paused_and_closing_releases(client):
    _control(client, title="Erst R7 testen", control="pause", scope="all")
    data = client.post("/board/next", json={}, headers=_bearer(AGENT)).get_json()
    assert data["task"] is None and data["paused"] is True
    assert (data["pause"]["task"], data["pause"]["reason"], data["pause"]["by"]) == ("api#2", "Erst R7 testen",
                                                                                      "human")
    assert client.patch(f"{URL}/2", json={"status": "done"}, headers=_bearer(HUMAN)).status_code == 200
    data = client.post("/board/next", json={}, headers=_bearer(AGENT)).get_json()
    assert data["task"]["ref"] == "api#1" and data["control"] == {"pauses": [], "hints": []}


def test_comment_on_a_work_ticket_shows_the_open_pause(client):
    _control(client, title="Anhalten", control="pause", scope="project")
    resp = client.post(f"{URL}/1/comments", json={"body": "Zwischenstand"}, headers=_bearer(AGENT))
    assert resp.status_code == 201
    assert [p["task"] for p in resp.get_json()["control"]["pauses"]] == ["api#2"]
    for path in ("/board/tasks", f"{URL}/1", "/board"):
        assert client.get(path, headers=_bearer(AGENT if path != "/board" else HUMAN)).get_json()["control"]["pauses"]


def test_hint_acknowledged_shows_on_the_card_and_leaves_control(client):
    _control(client, title="Ab jetzt zuerst die Tests", control="hint", scope="all")
    assert client.get("/board/tasks", headers=_bearer(AGENT)).get_json()["control"]["hints"][0]["task"] == "api#2"
    resp = client.post(f"{URL}/2/comments", json={"body": "Verstanden", "author_name": "cc"}, headers=_bearer(AGENT))
    assert resp.status_code == 201 and resp.get_json()["control"]["hints"] == []
    card = client.get(f"{URL}/2", headers=_bearer(HUMAN)).get_json()
    assert card["kind"] == "control" and card["directive"]["ack_by"] == "cc (agent)" and card["status"] == "todo"


def test_ordinary_ticket_with_pause_text_triggers_nothing(client):
    client.post("/board/tasks", json={"project": "api", "title": "Pause, alle Agenten anhalten",
                                      "description": "kind=control"}, headers=_bearer(AGENT))
    data = client.post("/board/next", json={}, headers=_bearer(AGENT)).get_json()
    assert data["task"] is not None and "paused" not in data


@pytest.mark.parametrize("body", [{"control": "stopp"}, {"control": "pause", "scope": "welt"}, {"control": 1},
                                  {"kind": "control"}])
def test_control_fields_are_checked(client, body):
    payload = {"project": "api", "title": "x", "kind": "control", **body}
    assert client.post("/board/tasks", json=payload, headers=_bearer(HUMAN)).status_code == 400


# ── MCP ─────────────────────────────────────────────────────────────────────

pytest.importorskip("mcp")


@pytest.fixture
def live(app, client, monkeypatch):
    from werkzeug.serving import make_server

    import conclave.mcp_server as server
    srv = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(server, "API_URL", f"http://127.0.0.1:{srv.server_port}")
    monkeypatch.setattr(server, "MODE", "agent")
    monkeypatch.setattr(server, "_confirmed_token", None)
    monkeypatch.setenv("CONCLAVE_AGENT_KEY", AGENT)
    yield server
    srv.shutdown()
    thread.join(timeout=5)


def test_mcp_next_reports_the_pause_and_every_tool_carries_control(live, client):
    _control(client, title="Bitte anhalten", control="pause", scope="all")
    out = live.conclave_board_next()
    assert out["paused"] is True and out["task"] == "api#2" and out["reason"] == "Bitte anhalten"
    assert live.conclave_board_list()["control"]["pauses"]
    assert live.conclave_board_get("api#1")["control"]["pauses"]
    assert live.conclave_board_comment("api#1", "Zwischenstand", author="cc")["control"]["pauses"]
    assert live.conclave_board_create("api", "Neu")["control"]["pauses"]
    note = live.conclave_board_list()["control"]["note"]
    assert "Anweisung des Menschen" in note


def test_mcp_tools_show_empty_control_without_directives(live):
    assert live.conclave_board_list()["control"] == {"pauses": [], "hints": []}
