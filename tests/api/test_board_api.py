"""B3: Board-REST-API mit Mensch- und Agent-Token, Import aus einem JSON-Export."""

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("flask")

from conclave.cli.config import ConclaveConfig  # noqa: E402

HUMAN = "cvh_mensch-token"
AGENT = "cva_agent-token"

# Echter Export (nur lokal, Kopie im Scratchpad): CONCLAVE_TEST_BOARD_EXPORT=<pfad>
REAL_EXPORT = os.environ.get("CONCLAVE_TEST_BOARD_EXPORT", "")


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(tmp_path):
    from conclave.api.server import _build_app
    app, _ = _build_app(ConclaveConfig(db_path=tmp_path / "c.db", api_key=HUMAN, agent_api_key=AGENT))
    app.config["TESTING"] = True
    c = app.test_client()
    assert c.post("/board/projects", json={"slug": "api", "name": "API"}, headers=_bearer(HUMAN)).status_code == 201
    return c


def _task(c, token, **body):
    resp = c.post("/board/tasks", json={"project": "api", "title": "T", **body}, headers=_bearer(token))
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


def test_overview_and_change_counter(client):
    assert client.get("/board", headers=_bearer(AGENT)).status_code == 403   # UI-Uebersicht nur fuer Menschen
    data = client.get("/board", headers=_bearer(HUMAN)).get_json()
    assert data["statuses"] == ["todo", "doing", "review", "done"]
    assert [p["slug"] for p in data["projects"]] == ["api"]
    before = client.get("/board/changes", headers=_bearer(HUMAN)).get_json()["changes"]
    _task(client, AGENT)
    assert client.get("/board/changes", headers=_bearer(HUMAN)).get_json()["changes"] > before


def test_agent_workflow_and_the_done_rule(client):
    task = _task(client, AGENT, description="## Abnahme\n- Tests", tags=["b3"])
    assert (task["ref"], task["status"], task["version"]) == ("api#1", "todo", 1)
    taken = client.post("/board/next", json={"project": "api"}, headers=_bearer(AGENT)).get_json()["task"]
    assert (taken["ref"], taken["status"]) == ("api#1", "doing")
    url = "/board/projects/api/tasks/1"
    assert client.post(url + "/comments", json={"body": "Branch board, Commit abc"},
                       headers=_bearer(AGENT)).status_code == 201
    assert client.patch(url, json={"status": "review"}, headers=_bearer(AGENT)).get_json()["status"] == "review"
    resp = client.patch(url, json={"status": "done"}, headers=_bearer(AGENT))
    assert resp.status_code == 403 and resp.get_json()["type"] == "HumanOnly"
    assert client.patch(url, json={"status": "done"}, headers=_bearer(HUMAN)).status_code == 200
    detail = client.get(url, headers=_bearer(AGENT)).get_json()
    assert detail["comments"][0]["origin"] == "agent"
    history = client.get(url + "/history", headers=_bearer(AGENT)).get_json()["history"]
    assert [(h["new"], h["origin"]) for h in history] == [("doing", "agent"), ("review", "agent"), ("done", "human")]


def test_human_only_routes_for_agents(client):
    _task(client, HUMAN)
    for method, url, body in [("POST", "/board/projects", {"slug": "x", "name": "X"}),
                              ("PUT", "/board/projects/api", {"name": "neu"}),
                              ("DELETE", "/board/projects/api", None),
                              ("DELETE", "/board/projects/api/tasks/1", None),
                              ("POST", "/board/import", {"projects": []})]:
        resp = client.open(url, method=method, json=body, headers=_bearer(AGENT))
        assert resp.status_code == 403, (method, url)
    assert client.delete("/board/projects/api/tasks/1", headers=_bearer(HUMAN)).status_code == 204


def test_validation_and_not_found(client):
    _task(client, HUMAN)
    url = "/board/projects/api/tasks/1"
    for body in ({"unbekannt": 1}, {"tags": "x"}, {"index": "1"}, {"human": "ja"}, {"status": "fertig"},
                 {"title": "  "}):
        assert client.patch(url, json=body, headers=_bearer(HUMAN)).status_code == 400, body
    assert client.get("/board/projects/api/tasks/9", headers=_bearer(HUMAN)).status_code == 404
    assert client.get("/board/tasks?project=gibtsnicht", headers=_bearer(HUMAN)).status_code == 404
    assert client.post("/board/tasks", json=["kein objekt"], headers=_bearer(HUMAN)).status_code == 400


def test_comment_edit_only_own_human_comments(client):
    _task(client, HUMAN)
    url = "/board/projects/api/tasks/1/comments"
    mine = client.post(url, json={"body": "meins"}, headers=_bearer(HUMAN)).get_json()
    theirs = client.post(url, json={"body": "vom Agenten"}, headers=_bearer(AGENT)).get_json()
    assert client.put(f"/board/comments/{mine['id']}", json={"body": "neu"}, headers=_bearer(HUMAN)).status_code == 200
    assert client.put(f"/board/comments/{theirs['id']}", json={"body": "x"}, headers=_bearer(HUMAN)).status_code == 403
    assert client.delete(f"/board/comments/{mine['id']}", headers=_bearer(AGENT)).status_code == 403


def test_list_and_search(client):
    _task(client, HUMAN, title="Login leer", tags=["frontend"])
    _task(client, HUMAN, title="fertig", status="done")
    assert [t["ref"] for t in client.get("/board/tasks?project=api", headers=_bearer(AGENT)).get_json()["tasks"]] == ["api#1"]
    all_tasks = client.get("/board/tasks?project=api&include_done=true", headers=_bearer(AGENT)).get_json()["tasks"]
    assert len(all_tasks) == 2
    assert [t["ref"] for t in client.get("/board/search?q=frontend", headers=_bearer(AGENT)).get_json()["tasks"]] == ["api#1"]


# ── Import ────────────────────────────────────────────────────────────────

def test_import_is_complete_without_claimed_origin_and_idempotent(client, board_sample_export):
    data = (json.loads(Path(REAL_EXPORT).read_text(encoding="utf-8"))
            if REAL_EXPORT and Path(REAL_EXPORT).is_file() else board_sample_export)
    expected_tasks = sum(len(p["tasks"]) for p in data["projects"])
    expected_comments = sum(len(t["comments"]) for p in data["projects"] for t in p["tasks"]
                            if any(c["body"].strip() for c in t["comments"]))
    first = client.post("/board/import", json=data, headers=_bearer(HUMAN)).get_json()
    assert first["tasks_imported"] == expected_tasks and first["tasks_skipped"] == 0
    assert first["comments_imported"] >= expected_comments
    second = client.post("/board/import", json=data, headers=_bearer(HUMAN)).get_json()
    assert (second["tasks_imported"], second["tasks_skipped"], second["projects_created"]) == (0, expected_tasks, 0)
    assert len(second["skipped_refs"]) == expected_tasks

    slug = data["projects"][0]["slug"]
    source = data["projects"][0]["tasks"][0]
    number = int(source["key"].split("#")[1])
    detail = client.get(f"/board/projects/{slug}/tasks/{number}", headers=_bearer(HUMAN)).get_json()
    assert (detail["title"], detail["status"], detail["human"]) == (source["title"], source["status"], source["human"])
    assert all(c["origin"] is None for c in detail["comments"])                 # keine behauptete Herkunft
    assert [c["author_name"] for c in detail["comments"]] == [
        c["author"] for c in sorted(source["comments"], key=lambda c: c["created_at"]) if c["body"].strip()]
    # die naechste Nummer liegt hinter der hoechsten importierten
    highest = max(int(t["key"].split("#")[1]) for t in data["projects"][0]["tasks"])
    new = client.post("/board/tasks", json={"project": slug, "title": "neu"}, headers=_bearer(HUMAN)).get_json()
    assert new["number"] == highest + 1


def test_imported_human_only_ticket_stays_protected(client, board_sample_export):
    client.post("/board/import", json=board_sample_export, headers=_bearer(HUMAN))
    assert client.post("/board/next", json={"project": "conclave"}, headers=_bearer(AGENT)).get_json()["task"] is None
    assert client.patch("/board/projects/conclave/tasks/13", json={"title": "x"},
                        headers=_bearer(AGENT)).status_code == 403


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d.update(projects="x"), "projects"),
    (lambda d: d["projects"][0]["tasks"][0].update(status="archiv"), "Unbekannte Status"),
    (lambda d: d["projects"][0]["tasks"][0].update(key="anders#7"), "passt nicht"),
    (lambda d: d["projects"][0]["tasks"][1].update(key="conclave#7"), "doppelt"),
    (lambda d: d["projects"][0]["tasks"][0].update(human="ja"), "human"),
    (lambda d: d["projects"][0]["tasks"][0].update(created_at="gestern"), "Zeitpunkt"),
    (lambda d: d["projects"][0].update(slug="Mit Leerzeichen"), "Kurzname"),
])
def test_broken_export_writes_nothing(client, board_sample_export, mutate, message):
    data = board_sample_export
    mutate(data)
    before = client.get("/board/changes", headers=_bearer(HUMAN)).get_json()["changes"]
    resp = client.post("/board/import", json=data, headers=_bearer(HUMAN))
    assert resp.status_code == 400 and resp.get_json()["type"] == "ImportFormatError"
    assert message in resp.get_json()["error"]
    assert client.get("/board/changes", headers=_bearer(HUMAN)).get_json()["changes"] == before


def test_board_disabled_without_service():
    from unittest.mock import MagicMock

    from conclave.api.app import create_app
    resp = create_app(MagicMock()).test_client().get("/board")
    assert resp.status_code == 503 and resp.get_json()["type"] == "BoardDisabled"


# ── Review B3 ─────────────────────────────────────────────────────────────

def test_spec_paths_have_no_flask_converters_and_typed_numbers():
    spec = json.loads((Path(__file__).resolve().parents[2] / "static" / "openapi.json").read_text(encoding="utf-8"))
    assert not [p for p in spec["paths"] if "<" in p or ">" in p]
    op = spec["paths"]["/board/projects/{slug}/tasks/{number}"]["get"]
    params = {p["name"]: p["schema"]["type"] for p in op["parameters"]}
    assert params == {"slug": "string", "number": "integer"}


def test_import_counts_a_number_taken_meanwhile_as_skipped(client, board_sample_export, monkeypatch):
    """Vergibt jemand zwischen Pruefen und Schreiben dieselbe Nummer, kein 500, sondern uebersprungen."""
    client.post("/board/import", json=board_sample_export, headers=_bearer(HUMAN))
    from conclave.infrastructure.sqlite.board_repository import SQLiteBoardRepository
    monkeypatch.setattr(SQLiteBoardRepository, "get_task", lambda self, slug, number: None)  # Pruefung "sieht" nichts
    resp = client.post("/board/import", json=board_sample_export, headers=_bearer(HUMAN))
    monkeypatch.undo()
    assert resp.status_code == 200
    data = resp.get_json()
    assert (data["tasks_imported"], data["tasks_skipped"]) == (0, 3)
    assert sorted(data["skipped_refs"]) == ["conclave#13", "conclave#2", "conclave#7"]
    comments = client.get("/board/projects/conclave/tasks/7/comments", headers=_bearer(HUMAN)).get_json()["comments"]
    assert len(comments) == 2                                                 # nichts doppelt


@pytest.mark.parametrize("body", [{"human": "false"}, {"title": 5}, {"description": ["x"]}, {"tags": ["a", 1]},
                                  {"status": 3}, {"unbekannt": 1}])
def test_create_validates_like_patch(client, body):
    resp = client.post("/board/tasks", json={"project": "api", "title": "T", **body}, headers=_bearer(HUMAN))
    assert resp.status_code == 400 and resp.get_json()["type"] == "ValidationError", body


def test_import_size_limit(client, monkeypatch):
    import conclave.api.app as app_module
    monkeypatch.setattr(app_module, "BOARD_IMPORT_MAX_BYTES", 100)
    resp = client.post("/board/import", json={"projects": [], "x": "y" * 200}, headers=_bearer(HUMAN))
    assert resp.status_code == 413 and resp.get_json()["type"] == "ImportTooLarge"


def test_import_size_limit_without_content_length(client, monkeypatch):
    import io

    import conclave.api.app as app_module
    monkeypatch.setattr(app_module, "BOARD_IMPORT_MAX_BYTES", 100)
    body = json.dumps({"projects": [], "x": "y" * 200}).encode()
    # wie hinter waitress: chunked, ohne Content-Length, Eingabe als abgeschlossen gemeldet
    resp = client.post("/board/import", input_stream=io.BytesIO(body),
                       headers={**_bearer(HUMAN), "Content-Type": "application/json", "Transfer-Encoding": "chunked"},
                       environ_overrides={"wsgi.input_terminated": True, "CONTENT_LENGTH": ""})
    assert resp.status_code == 413 and resp.get_json()["type"] == "ImportTooLarge"


def test_import_rejects_invalid_json(client):
    resp = client.post("/board/import", data=b"{kaputt", headers={**_bearer(HUMAN), "Content-Type": "application/json"})
    assert resp.status_code == 400 and resp.get_json()["type"] == "ImportFormatError"
