"""P2 (conclave#57): Vorhaben ueber die REST-API.

- Anlegen und Aendern nur mit dem Mensch-Token (Agent und Reviewer: 403).
- Tickets ueber ``/board/projects/<p>/initiatives/<v>/tasks/<n>`` und ``/tasks/<nummer>``
  liefern dasselbe Ticket; ``next`` nimmt beide Referenzen.
- PATCH ``initiative`` ordnet zu (nur Mensch); ein Agent aendert dabei nichts.
"""

import pytest

pytest.importorskip("flask")

from conclave.cli.config import ConclaveConfig  # noqa: E402

HUMAN, AGENT, REVIEWER = "cvh_p2-mensch", "cva_p2-agent", "cvr_p2-reviewer"


def _h(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def c(tmp_path):
    from conclave.api.server import _build_app
    app, _ = _build_app(ConclaveConfig(db_path=tmp_path / "c.db", api_key=HUMAN, agent_api_key=AGENT,
                                       reviewer_api_key=REVIEWER))
    app.config["TESTING"] = True
    client = app.test_client()
    assert client.post("/board/projects", json={"slug": "conclave", "name": "Conclave"},
                       headers=_h(HUMAN)).status_code == 201
    return client


def test_only_the_human_creates_and_changes_initiatives(c):
    body = {"slug": "sich", "title": "Sicherheit"}
    for token in (AGENT, REVIEWER):
        assert c.post("/board/projects/conclave/initiatives", json=body, headers=_h(token)).status_code == 403
    created = c.post("/board/projects/conclave/initiatives", json=body, headers=_h(HUMAN))
    assert created.status_code == 201 and created.get_json()["slug"] == "sich"
    for token in (AGENT, REVIEWER):
        assert c.put("/board/projects/conclave/initiatives/sich", json={"rank": -1},
                     headers=_h(token)).status_code == 403
    changed = c.put("/board/projects/conclave/initiatives/sich", json={"title": "Sicherheit v0.7", "rank": -1},
                    headers=_h(HUMAN))
    assert changed.status_code == 200 and changed.get_json()["rank"] == -1
    listed = c.get("/board/projects/conclave/initiatives", headers=_h(AGENT))
    assert listed.status_code == 200 and [i["slug"] for i in listed.get_json()["initiatives"]] == ["sich"]


def test_both_references_return_the_same_ticket(c):
    c.post("/board/projects/conclave/initiatives", json={"slug": "sich", "title": "S"}, headers=_h(HUMAN))
    for title in ("R1", "R2", "R3"):
        assert c.post("/board/tasks", json={"project": "conclave", "title": title, "initiative": "sich"},
                      headers=_h(AGENT)).status_code == 201
    by_initiative = c.get("/board/projects/conclave/initiatives/sich/tasks/3", headers=_h(REVIEWER))
    by_number = c.get("/board/projects/conclave/tasks/3", headers=_h(REVIEWER))
    assert by_initiative.status_code == by_number.status_code == 200
    a, b = by_initiative.get_json(), by_number.get_json()
    assert a["ref"] == b["ref"] == "conclave#3" and a["initiative_ref"] == b["initiative_ref"] == "conclave/sich-3"
    assert c.get("/board/projects/conclave/initiatives/sich/tasks/9", headers=_h(AGENT)).status_code == 404
    taken = c.post("/board/next", json={"task": "conclave/sich-2"}, headers=_h(AGENT)).get_json()
    assert taken["task"]["ref"] == "conclave#2" and taken["task"]["status"] == "doing"


def test_unknown_initiative_when_creating_a_ticket(c):
    resp = c.post("/board/tasks", json={"project": "conclave", "title": "T", "initiative": "gibtsnicht"},
                  headers=_h(AGENT))
    assert resp.status_code == 404 and resp.get_json()["type"] == "InitiativeNotFound"
    assert c.post("/board/tasks", json={"project": "conclave", "title": "T", "initiative": 3},
                  headers=_h(AGENT)).status_code == 400


def test_patch_assigns_only_for_the_human(c):
    c.post("/board/projects/conclave/initiatives", json={"slug": "sich", "title": "S"}, headers=_h(HUMAN))
    c.post("/board/tasks", json={"project": "conclave", "title": "alt"}, headers=_h(HUMAN))
    before = c.get("/board/projects/conclave/tasks/1", headers=_h(HUMAN)).get_json()
    refused = c.patch("/board/projects/conclave/tasks/1", json={"title": "neu", "initiative": "sich"},
                      headers=_h(AGENT))
    assert refused.status_code == 403
    after = c.get("/board/projects/conclave/tasks/1", headers=_h(HUMAN)).get_json()
    assert (after["title"], after["version"], after["initiative_ref"]) == ("alt", before["version"], None)
    done = c.patch("/board/projects/conclave/tasks/1", json={"title": "neu", "initiative": "sich"},
                   headers=_h(HUMAN))
    assert done.status_code == 200
    assert (done.get_json()["title"], done.get_json()["initiative_ref"]) == ("neu", "conclave/sich-1")
    removed = c.patch("/board/projects/conclave/tasks/1", json={"initiative": None}, headers=_h(HUMAN))
    assert removed.get_json()["initiative_ref"] is None


def test_patch_with_a_stale_version_and_only_initiative_is_a_conflict(c):
    c.post("/board/projects/conclave/initiatives", json={"slug": "sich", "title": "S"}, headers=_h(HUMAN))
    c.post("/board/tasks", json={"project": "conclave", "title": "T"}, headers=_h(HUMAN))
    stale = c.get("/board/projects/conclave/tasks/1", headers=_h(HUMAN)).get_json()["version"]
    c.patch("/board/projects/conclave/tasks/1", json={"title": "anders"}, headers=_h(HUMAN))
    resp = c.patch("/board/projects/conclave/tasks/1", json={"initiative": "sich", "version": stale},
                   headers=_h(HUMAN))
    assert resp.status_code == 409
    assert c.get("/board/projects/conclave/tasks/1", headers=_h(HUMAN)).get_json()["initiative_ref"] is None
