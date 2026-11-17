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
