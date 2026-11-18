"""T3: versionierte Board-API.

- ``/board/v1/...`` ist die API; ``/board/...`` antwortet als Alias gleich, mit
  ``Deprecation``, ``Sunset`` und ``Link`` auf den Nachfolger.
- ``GET /board/versions`` ohne Token, die Angabe steht auch in ``/health``.
- Beide Apps (Board-Server und Personal) verhalten sich gleich.
- Die OpenAPI-Dateien sind aus den Routen erzeugt und aktuell (Drift).
"""

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from conclave_board.api.app import create_board_app
from conclave_board.api.versions import ALIAS_DEPRECATION, ALIAS_SUNSET, board_versions
from conclave_board.infrastructure.auth import StaticKeyAuthService
from conclave_board.server import open_board

ROOT = Path(__file__).resolve().parents[2]
HUMAN, AGENT, REVIEWER = "cvh_mensch", "cva_agent", "cvr_reviewer"


def _h(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(params=["board", "personal"])
def client(request, tmp_path):
    board, _conn = open_board(db_path=tmp_path / "board.db", config_dir=tmp_path / "config")
    auth = StaticKeyAuthService(HUMAN, AGENT, REVIEWER)
    if request.param == "board":
        app = create_board_app(board, auth)
    else:
        from conclave.api.app import create_app
        app = create_app(MagicMock(), auth_service=auth, board=board)
    c = app.test_client()
    assert c.post("/board/v1/projects", json={"slug": "api", "name": "API"}, headers=_h(HUMAN)).status_code == 201
    assert c.post("/board/v1/tasks", json={"project": "api", "title": "Erstes"}, headers=_h(AGENT)).status_code == 201
    return c


@pytest.mark.parametrize("path", ["", "/tasks?project=api", "/projects/api/tasks/1", "/projects/api/tasks/1/history",
                                  "/changes", "/search?q=Erstes"])
def test_alias_answers_like_v1_with_deprecation_headers(client, path):
    v1 = client.get("/board/v1" + path, headers=_h(HUMAN))
    alias = client.get("/board" + path, headers=_h(HUMAN))
    assert v1.status_code == alias.status_code == 200
    assert alias.get_json() == v1.get_json()
    assert "Deprecation" not in v1.headers and "Sunset" not in v1.headers
    assert alias.headers["Deprecation"] == ALIAS_DEPRECATION
    assert alias.headers["Sunset"] == ALIAS_SUNSET
    assert alias.headers["Link"] == f'</board/v1{path.split("?")[0]}>; rel="successor-version"'


def test_alias_headers_also_on_errors_and_writes(client):
    missing = client.get("/board/projects/api/tasks/99", headers=_h(HUMAN))
    assert missing.status_code == 404 and missing.headers["Deprecation"] == ALIAS_DEPRECATION
    written = client.post("/board/projects/api/tasks/1/comments", json={"body": "x"}, headers=_h(AGENT))
    assert written.status_code == 201 and written.headers["Sunset"] == ALIAS_SUNSET


def test_access_rules_are_the_same_under_both_prefixes(client):
    for prefix in ("/board/v1", "/board"):
        assert client.get(prefix, headers=_h(AGENT)).status_code == 403                 # Uebersicht nur Mensch
        assert client.get(prefix + "/tasks", headers=_h(REVIEWER)).status_code == 200
        assert client.post(prefix + "/tasks", json={"project": "api", "title": "R"},
                           headers=_h(REVIEWER)).status_code == 403
        assert client.get(prefix + "/tasks").status_code == 401


def test_versions_are_public_and_in_health(client):
    resp = client.get("/board/versions")
    assert resp.status_code == 200 and resp.get_json() == board_versions()
    assert resp.get_json()["current"] == "v1"
    assert client.get("/health").get_json()["board_api"] == board_versions()


# ── OpenAPI aus den Routen (Drift) ──────────────────────────────────────────

def _generator():
    spec = importlib.util.spec_from_file_location("gen_openapi", ROOT / "scripts" / "gen-openapi.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_openapi_files_are_generated_from_the_current_routes():
    gen = _generator()
    for path in gen.OUTS:
        assert json.loads(path.read_text(encoding="utf-8")) == gen.personal_spec(), path
    assert json.loads(gen.BOARD_V1_OUT.read_text(encoding="utf-8")) == gen.board_v1_spec(), \
        "python scripts/gen-openapi.py ausfuehren"


def test_board_v1_contract_contains_only_v1_and_versions():
    spec = json.loads((ROOT / "packages" / "board" / "openapi" / "board-v1.json").read_text(encoding="utf-8"))
    paths = set(spec["paths"])
    assert paths and all(p == "/board/v1" or p.startswith("/board/v1/") or p == "/board/versions" for p in paths)
    assert {"/board/v1", "/board/v1/tasks", "/board/v1/next", "/board/versions"} <= paths
    operations = [op for item in spec["paths"].values() for op in item.values()]
    assert len({op["operationId"] for op in operations}) == len(operations)
    assert not any(op.get("deprecated") for op in operations)


def test_personal_spec_marks_the_alias_as_deprecated():
    spec = json.loads((ROOT / "static" / "openapi.json").read_text(encoding="utf-8"))
    alias = [op for p, item in spec["paths"].items()
             if (p == "/board" or p.startswith("/board/")) and not p.startswith("/board/v1")
             and p != "/board/versions" for op in item.values()]
    assert alias and all(op["deprecated"] is True for op in alias)
    v1 = [op for p, item in spec["paths"].items() if p.startswith("/board/v1") for op in item.values()]
    assert len(v1) == len(alias) and not any(op.get("deprecated") for op in v1)


def test_alias_headers_on_401_and_403(client):
    """Review T3: Auch Antworten der Zugriffsschicht (vor dem Blueprint) tragen die Abkuendigung."""
    unauthenticated = client.get("/board/tasks")
    forbidden = client.get("/board", headers=_h(AGENT))
    assert unauthenticated.status_code == 401 and forbidden.status_code == 403
    for resp in (unauthenticated, forbidden):
        assert resp.headers["Deprecation"] == ALIAS_DEPRECATION and resp.headers["Sunset"] == ALIAS_SUNSET
    assert "Deprecation" not in client.get("/board/v1/tasks").headers
