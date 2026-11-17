"""T4: Erweiterungspunkte des Kerns, je mit einer Test-Erweiterung (ohne Team-Code).

- Token-Pruefung: Eine Erweiterung liefert Principals mit Konto (``actor_id``) und
  erlaubten Projekten (``projects``). Die Herkunft im Verlauf nennt das Konto; fremde
  Projekte sind nicht sichtbar (404), Listen und next_task enthalten sie nicht.
- Blueprints: weitere Routen laufen durch Anmeldung und Zugriffsschicht; fuer Agenten
  stehen sie nicht auf der Allowlist.
- Migrationsreihen: eine Erweiterung bringt eine eigene Reihe mit eigener Tracking-Tabelle.

Personal (Principal ohne Konto und Projekte) verhaelt sich unveraendert; das pruefen die
bestehenden Tests.
"""

import sqlite3

import pytest
from flask import Blueprint, g, jsonify

from conclave_board.api.app import create_board_app
from conclave_board.domain.principal import Principal
from conclave_board.infrastructure.migrations import Migration, applied_ids, run_extension_migrations
from conclave_board.server import open_board

ADMIN = Principal("human", actor_id="u-admin", name="Admin")
ALICE_AGENT = Principal("agent", actor_id="u-alice", projects=frozenset({"api"}), name="Alice")
BOB = Principal("human", actor_id="u-bob", projects=frozenset({"web"}), name="Bob")


class AccountAuth:
    """Test-Erweiterung: Tokens -> Principals mit Konto und Projekten."""

    TOKENS = {"t-admin": ADMIN, "t-alice-agent": ALICE_AGENT, "t-bob": BOB}

    def authenticate(self, token):
        return self.TOKENS.get(token)


def _h(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(tmp_path):
    board, _conn = open_board(db_path=tmp_path / "board.db", config_dir=tmp_path / "config")
    ext = Blueprint("ext", __name__)

    @ext.get("/ext/whoami")
    def ext_whoami():
        return jsonify({"actor": g.principal.actor_id}), 200

    c = create_board_app(board, AccountAuth(), blueprints=[ext]).test_client()
    for slug in ("api", "web"):
        assert c.post("/board/v1/projects", json={"slug": slug, "name": slug}, headers=_h("t-admin")).status_code == 201
        assert c.post("/board/v1/tasks", json={"project": slug, "title": f"{slug} 1"},
                      headers=_h("t-admin")).status_code == 201
    return c


def test_history_names_the_account(client):
    created = client.post("/board/v1/tasks", json={"project": "api", "title": "vom Agenten"}, headers=_h("t-alice-agent"))
    assert created.status_code == 201
    history = client.get("/board/v1/projects/api/tasks/2/history", headers=_h("t-admin")).get_json()["history"]
    assert history[0]["origin"] == "agent" and history[0]["actor_id"] == "u-alice"
    client.post("/board/v1/projects/api/tasks/2/comments", json={"body": "x"}, headers=_h("t-admin"))
    comments = client.get("/board/v1/projects/api/tasks/2", headers=_h("t-admin")).get_json()["comments"]
    assert comments[-1]["origin"] == "human" and comments[-1]["actor_id"] == "u-admin"


def test_scoped_token_sees_only_its_projects(client):
    agent = _h("t-alice-agent")
    tasks = client.get("/board/v1/tasks", headers=agent).get_json()["tasks"]
    assert {t["project"] for t in tasks} == {"api"}
    assert client.get("/board/v1/search?q=1", headers=agent).get_json()["tasks"][0]["project"] == "api"
    assert len(client.get("/board/v1/search?q=1", headers=agent).get_json()["tasks"]) == 1
    for path in ("/board/v1/projects/web/tasks/1", "/board/v1/projects/web/tasks/1/history",
                 "/board/v1/tasks?project=web", "/board/v1/projects/web/initiatives"):
        resp = client.get(path, headers=agent)
        assert resp.status_code == 404 and resp.get_json()["type"] == "ProjectNotFound", path
    assert client.post("/board/v1/tasks", json={"project": "web", "title": "x"}, headers=agent).status_code == 404
    assert client.post("/board/v1/projects/web/tasks/1/comments", json={"body": "x"}, headers=agent).status_code == 404
    # Alias wie v1
    assert client.get("/board/projects/web/tasks/1", headers=agent).status_code == 404


def test_next_task_never_hands_out_foreign_tickets(client):
    agent = _h("t-alice-agent")
    assert client.post("/board/v1/next", json={"task": "web#1"}, headers=agent).status_code == 404
    assert client.post("/board/v1/next", json={"project": "web"}, headers=agent).status_code == 404
    first = client.post("/board/v1/next", json={}, headers=agent).get_json()
    assert first["task"]["ref"] == "api#1"
    assert client.post("/board/v1/next", json={}, headers=agent).get_json()["task"] is None   # web#1 bleibt liegen


def test_scoped_human_overview_lists_only_own_projects(client):
    overview = client.get("/board/v1", headers=_h("t-bob")).get_json()
    assert [p["slug"] for p in overview["projects"]] == ["web"]
    assert {p["slug"] for p in client.get("/board/v1", headers=_h("t-admin")).get_json()["projects"]} == {"api", "web"}


def test_extension_blueprint_goes_through_auth_and_access(client):
    assert client.get("/ext/whoami").status_code == 401
    assert client.get("/ext/whoami", headers=_h("t-admin")).get_json() == {"actor": "u-admin"}
    assert client.get("/ext/whoami", headers=_h("t-alice-agent")).status_code == 403   # nicht auf der Allowlist


def test_extension_migration_series_has_its_own_table(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "x.db"), isolation_level="IMMEDIATE")
    series = [Migration(id="001_ext", description="Test", statements=("CREATE TABLE ext_items (id TEXT)",))]
    assert run_extension_migrations(conn, False, series, "ext_test_migrations") == ["001_ext"]
    assert run_extension_migrations(conn, False, series, "ext_test_migrations") == []
    assert applied_ids(conn, False, "ext_test_migrations") == {"001_ext"}
    for bad in ("board_migrations", "_migrations", "x; DROP TABLE y", "Ext_migrations", "ext_items"):
        with pytest.raises(ValueError):
            run_extension_migrations(conn, False, series, bad)


def test_principal_without_accounts_behaves_like_personal():
    plain = Principal("agent")
    assert plain.actor_id is None and plain.projects is None and plain.sees("irgendwas")
    from conclave_board.application.board import BoardService
    assert BoardService.actor(plain) == ("agent", "agent")


# ── Review T4 (rot): B1 Steuertickets, B2 Import/Projekte, B3 eigene Kommentare, V1 alle Routen ──

def _control_tickets(client):
    """Pause und Hinweis im Projekt web, ein Hinweis fuer alle (vom Admin)."""
    for body in ({"project": "web", "title": "Pause web", "kind": "control", "control": "pause",
                  "description": "GEHEIM-WEB"},
                 {"project": "web", "title": "Hinweis web", "kind": "control", "control": "hint",
                  "description": "GEHEIM-WEB-HINWEIS"},
                 {"project": "api", "title": "Hinweis alle", "kind": "control", "control": "hint",
                  "scope": "all", "description": "fuer alle"}):
        assert client.post("/board/v1/tasks", json=body, headers=_h("t-admin")).status_code == 201


def test_control_tickets_of_foreign_projects_are_invisible_and_ineffective(client):
    _control_tickets(client)
    agent = _h("t-alice-agent")
    for path in ("/board/v1/tasks", "/board/v1/search?q=1", "/board/v1/projects/api/tasks/1"):
        resp = client.get(path, headers=agent)
        text = resp.get_data(as_text=True)
        assert resp.status_code == 200 and "GEHEIM-WEB" not in text and "Pause web" not in text, path
        control = resp.get_json()["control"]
        assert control["pauses"] == [] and [h["reason"] for h in control["hints"]] == ["Hinweis alle"], path
    taken = client.post("/board/v1/next", json={}, headers=agent).get_json()
    assert taken.get("paused") is not True and taken["task"]["ref"] == "api#1"       # fremde Pause stoppt nicht
    # Fuer den Admin wirkt die Pause in web weiter
    admin_view = client.get("/board/v1/tasks", headers=_h("t-admin")).get_json()["control"]
    assert [p["reason"] for p in admin_view["pauses"]] == ["Pause web"]


def test_pause_for_all_projects_still_stops_a_scoped_agent(client):
    assert client.post("/board/v1/tasks", json={"project": "web", "title": "Alle anhalten", "kind": "control",
                                                "control": "pause", "scope": "all"},
                       headers=_h("t-admin")).status_code == 201
    taken = client.post("/board/v1/next", json={}, headers=_h("t-alice-agent")).get_json()
    assert taken["paused"] is True and taken["task"] is None


def test_scoped_human_cannot_import_or_create_projects(client):
    bob = _h("t-bob")
    resp = client.post("/board/v1/import", json={"projects": [{"slug": "api", "name": "api", "tasks": []}]}, headers=bob)
    assert resp.status_code == 403 and "allen Projekten" in resp.get_json()["error"]
    assert client.post("/board/v1/projects", json={"slug": "neu", "name": "Neu"}, headers=bob).status_code == 403
    assert client.post("/board/v1/projects", json={"slug": "neu", "name": "Neu"}, headers=_h("t-admin")).status_code == 201


def test_comments_are_editable_only_by_their_own_account(client):
    admin_comment = client.post("/board/v1/projects/web/tasks/1/comments", json={"body": "vom Admin"},
                                headers=_h("t-admin")).get_json()
    bob_comment = client.post("/board/v1/projects/web/tasks/1/comments", json={"body": "von Bob"},
                              headers=_h("t-bob")).get_json()
    bob = _h("t-bob")
    assert client.put(f"/board/v1/comments/{admin_comment['id']}", json={"body": "x"}, headers=bob).status_code == 403
    assert client.delete(f"/board/v1/comments/{admin_comment['id']}", headers=bob).status_code == 403
    assert client.put(f"/board/v1/comments/{bob_comment['id']}", json={"body": "geaendert"}, headers=bob).status_code == 200
    # Kommentar in einem Projekt, das Bob nicht sieht: gibt es fuer ihn nicht
    api_comment = client.post("/board/v1/projects/api/tasks/1/comments", json={"body": "api"},
                              headers=_h("t-admin")).get_json()
    assert client.put(f"/board/v1/comments/{api_comment['id']}", json={"body": "x"}, headers=bob).status_code == 404
    assert client.delete(f"/board/v1/comments/{api_comment['id']}", headers=bob).status_code == 404
    assert client.put(f"/board/v1/comments/{admin_comment['id']}", json={"body": "ok"},
                      headers=_h("t-admin")).status_code == 200


# Erwartung je Route ohne <slug> fuer Bob (Mensch, nur web): wie sie die Projektgrenze wahrt
NO_SLUG = {
    ("GET", ""): "filtert", ("GET", "/changes"): "nur Zaehler", ("POST", "/projects"): 403,
    ("GET", "/tasks"): "filtert", ("POST", "/tasks"): 404, ("GET", "/search"): "filtert", ("POST", "/next"): 404,
    ("PUT", "/comments/<comment_id>"): 404, ("DELETE", "/comments/<comment_id>"): 404, ("POST", "/import"): 403,
    ("GET", "/stuck"): "filtert",
}


def test_every_board_route_respects_the_project_scope(client):
    """V1: alle Routen aus der url_map; neue Routen ohne Zuordnung lassen den Test scheitern."""
    api_comment = client.post("/board/v1/projects/api/tasks/1/comments", json={"body": "api"},
                              headers=_h("t-admin")).get_json()
    client.post("/board/v1/projects/api/initiatives", json={"slug": "sich", "title": "S"}, headers=_h("t-admin"))
    app = client.application
    rules = [(m, r.rule[len("/board/v1"):]) for r in app.url_map.iter_rules() if r.rule.startswith("/board/v1")
             for m in sorted(r.methods - {"HEAD", "OPTIONS"})]
    assert rules
    values = {"<slug>": "api", "<int:number>": "1", "<initiative>": "sich", "<comment_id>": api_comment["id"]}
    bob = _h("t-bob")
    for method, rule in rules:
        url = "/board/v1" + rule
        for placeholder, value in values.items():
            url = url.replace(placeholder, value)
        if rule == "/search":
            url += "?q=1"                                   # trifft "api 1" und "web 1"
        body = {"project": "api", "title": "x", "body": "x", "name": "x", "slug": "x", "state": "running"}
        resp = client.open(url, method=method, json=body, headers=bob)
        if "<slug>" in rule:
            assert resp.status_code == 404, (method, rule, resp.status_code)
            continue
        expected = NO_SLUG.get((method, rule))
        assert expected is not None, f"Route ohne Zuordnung im Test: {method} {rule}"
        if isinstance(expected, int):
            assert resp.status_code == expected, (method, rule, resp.status_code)
        elif expected == "filtert":
            assert resp.status_code == 200 and '"api' not in resp.get_data(as_text=True), (method, rule)
        else:
            assert resp.status_code == 200 and set(resp.get_json()) == {"changes"}
