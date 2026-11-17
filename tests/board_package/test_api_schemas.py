"""T3 (Review B1): Die echten Antworten der Board-API v1 passen zu ihren Schemas.

Die Schemas (``conclave_board.api.schemas``) sind der Vertrag in ``board-v1.json``; erst mit
ihnen erkennt ``oasdiff`` Brueche an Feldern. Dieser Test sorgt dafuer, dass Vertrag und
Verhalten nicht auseinanderlaufen: jede v1-Route wird aufgerufen, Statuscode, Pflichtfelder
und Typen der Antwort werden geprueft, ebenso dass Anfragen ausserhalb des Schemas scheitern.
"""

import pytest

from conclave_board.api.app import create_board_app
from conclave_board.api.schemas import BOARD_SCHEMAS, VERSIONS_SCHEMA
from conclave_board.infrastructure.auth import StaticKeyAuthService
from conclave_board.server import open_board

HUMAN, AGENT, REVIEWER = "cvh_mensch", "cva_agent", "cvr_reviewer"
TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict, "array": list}


def check(value, schema, where="$"):
    """Kleiner Validator fuer die genutzten Schemateile (type, nullable, required, properties, items, enum)."""
    if value is None:
        assert schema.get("nullable") or "type" not in schema, f"{where}: null nicht erlaubt"
        return
    kind = schema.get("type")
    if kind:
        expected = TYPES[kind]
        assert isinstance(value, expected) and not (kind in ("integer", "number") and isinstance(value, bool)), \
            f"{where}: {type(value).__name__} statt {kind}"
    if "enum" in schema:
        assert value in schema["enum"], f"{where}: {value!r} nicht in {schema['enum']}"
    if kind == "object":
        missing = set(schema.get("required", [])) - set(value)
        assert not missing, f"{where}: Pflichtfelder fehlen: {sorted(missing)}"
        for name, sub in schema.get("properties", {}).items():
            if name in value:
                check(value[name], sub, f"{where}.{name}")
    if kind == "array":
        for i, item in enumerate(value):
            check(item, schema.get("items", {}), f"{where}[{i}]")


@pytest.fixture
def api(tmp_path):
    board, _conn = open_board(db_path=tmp_path / "board.db", config_dir=tmp_path / "config")
    client = create_board_app(board, StaticKeyAuthService(HUMAN, AGENT, REVIEWER)).test_client()
    seen = set()

    def call(method, rel, token=HUMAN, body=None, query=""):
        resp = client.open("/board/v1" + rel.format(**IDS) + query, method=method, json=body,
                           headers={"Authorization": f"Bearer {token}"})
        key = (method, _rule(rel))
        entry = BOARD_SCHEMAS[key]
        assert resp.status_code == entry.get("status", 200), (key, resp.status_code, resp.get_json())
        if "response" in entry:
            check(resp.get_json(), entry["response"], f"{method} {rel}")
        if "request" in entry and body is not None:
            check(body, entry["request"], f"Anfrage {method} {rel}")
        seen.add(key)
        return resp.get_json()

    call.seen = seen
    call.client = client
    return call


IDS = {"slug": "api", "number": 1, "initiative": "sich", "comment_id": ""}
RULES = {"{slug}": "<slug>", "{number}": "<int:number>", "{initiative}": "<initiative>", "{comment_id}": "<comment_id>"}


def _rule(rel: str) -> str:
    for placeholder, rule in RULES.items():
        rel = rel.replace(placeholder, rule)
    return rel


def test_every_v1_route_answers_as_its_schema_says(api):
    api("POST", "/projects", body={"slug": "api", "name": "API"})
    api("PUT", "/projects/{slug}", body={"name": "API neu"})
    api("POST", "/projects/{slug}/initiatives", body={"slug": "sich", "title": "Sicherheit", "rank": 1})
    api("PUT", "/projects/{slug}/initiatives/{initiative}", body={"title": "Sicherheit 2"})
    api("GET", "/projects/{slug}/initiatives")
    api("POST", "/tasks", AGENT, body={"project": "api", "title": "Erstes", "tags": ["x"], "initiative": "sich"})
    api("POST", "/tasks", body={"project": "api", "title": "Hinweis", "kind": "control", "control": "hint",
                                "description": "lesen"})
    api("GET", "", query="")
    api("GET", "/changes")
    api("GET", "/tasks", AGENT, query="?project=api&status=todo&include_done=true")
    api("GET", "/search", REVIEWER, query="?q=Erstes")
    taken = api("POST", "/next", AGENT, body={"project": "api"})
    assert taken["task"]["ref"] == "api#1"
    api("GET", "/stuck", query="?project=api&minutes=1")
    released = api("POST", "/projects/{slug}/tasks/{number}/release", body={})
    assert released["status"] == "todo"
    taken = api("POST", "/next", AGENT, body={"project": "api"})
    api("GET", "/projects/{slug}/tasks/{number}", REVIEWER)
    api("GET", "/projects/{slug}/initiatives/{initiative}/tasks/{number}", REVIEWER)
    api("PATCH", "/projects/{slug}/tasks/{number}", AGENT, body={"status": "review", "version": taken["task"]["version"]})
    comment = api("POST", "/projects/{slug}/tasks/{number}/comments", AGENT, body={"body": "Branch x", "author_name": "cc"})
    api("GET", "/projects/{slug}/tasks/{number}/comments")
    api("GET", "/projects/{slug}/tasks/{number}/history", AGENT)
    api("POST", "/projects/{slug}/tasks/{number}/review", REVIEWER,
        body={"state": "rework", "comment": "Urteil: gelb", "blocking": 0, "suggestions": 1, "checked": "x @ 1"})
    api("GET", "/projects/{slug}/history")
    IDS["comment_id"] = comment["id"]
    try:
        # Eigene Kommentare aendert nur der Mensch; dafuer einen eigenen anlegen
        own = api("POST", "/projects/{slug}/tasks/{number}/comments", body={"body": "vom Menschen"})
        IDS["comment_id"] = own["id"]
        api("PUT", "/comments/{comment_id}", body={"body": "geaendert"})
        api("DELETE", "/comments/{comment_id}")
    finally:
        IDS["comment_id"] = ""
    api("POST", "/import", body={"projects": []})
    api("DELETE", "/projects/{slug}/tasks/{number}")
    api("DELETE", "/projects/{slug}")
    assert api.seen == set(BOARD_SCHEMAS), sorted(set(BOARD_SCHEMAS) - api.seen)


def test_versions_answer_as_their_schema_says(api):
    resp = api.client.get("/board/versions")
    check(resp.get_json(), VERSIONS_SCHEMA["response"])


@pytest.mark.parametrize("method, rel, body", [
    ("POST", "/tasks", {"project": "api", "title": "T", "unbekannt": 1}),
    ("PATCH", "/projects/api/tasks/1", {"unbekannt": 1}),
    ("POST", "/projects/api/initiatives", {"slug": "s", "title": "S", "unbekannt": 1}),
    ("POST", "/projects/api/tasks/1/review", {"state": "running", "unbekannt": 1}),
])
def test_requests_outside_a_closed_schema_are_rejected(api, method, rel, body):
    """Geschlossene Anfrage-Schemas (additionalProperties: false) spiegeln, dass die API Unbekanntes ablehnt."""
    key = (method, _rule(rel.replace("/api/", "/{slug}/").replace("/1", "/{number}")))
    assert BOARD_SCHEMAS[key]["request"].get("additionalProperties") is False
    client = api.client
    h = {"Authorization": f"Bearer {HUMAN}"}
    client.post("/board/v1/projects", json={"slug": "api", "name": "API"}, headers=h)
    client.post("/board/v1/tasks", json={"project": "api", "title": "T"}, headers=h)
    token = REVIEWER if rel.endswith("/review") else HUMAN
    resp = client.open("/board/v1" + rel, method=method, json=body, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 400, resp.get_json()


def test_required_request_fields_are_required(api):
    h = {"Authorization": f"Bearer {HUMAN}"}
    api.client.post("/board/v1/projects", json={"slug": "api", "name": "API"}, headers=h)
    for key, entry in BOARD_SCHEMAS.items():
        assert set(entry.get("request", {}).get("required", [])) <= set(entry.get("request", {}).get("properties", {})), key
    # Jedes fehlende Pflichtfeld ergibt einen Fehler des Clients, nie 500 (fehlendes Projekt: 404 wie bisher)
    for path, body in (("/tasks", {"project": "api"}), ("/tasks", {"title": "T"}), ("/projects", {"slug": "y"}),
                       ("/projects", {"name": "Y"}), ("/projects/api/initiatives", {"slug": "s"}),
                       ("/projects/api/initiatives", {"title": "S"})):
        resp = api.client.post("/board/v1" + path, json=body, headers=h)
        assert 400 <= resp.status_code < 500, (path, body, resp.status_code)
