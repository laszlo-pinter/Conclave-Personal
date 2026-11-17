"""T1: Board-App ohne Personal (``conclave_board.api.app``) und Start des Board-Servers."""

import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from conclave_board.api.app import create_board_app
from conclave_board.infrastructure.auth import StaticKeyAuthService
from conclave_board.runtime import file_security
from conclave_board.server import build_app, open_board

ROOT = Path(__file__).resolve().parents[2]
HUMAN, AGENT, REVIEWER = "cvh_mensch", "cva_agent", "cvr_reviewer"


@pytest.fixture
def client(tmp_path):
    board, _conn = open_board(db_path=tmp_path / "board.db", config_dir=tmp_path / "config")
    app = create_board_app(board, StaticKeyAuthService(HUMAN, AGENT, REVIEWER))
    return app.test_client()


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def test_needs_an_auth_service(tmp_path):
    board, _conn = open_board(db_path=tmp_path / "board.db", config_dir=tmp_path / "config")
    with pytest.raises(ValueError, match="auth_service"):
        create_board_app(board, None)


def test_health_is_public_and_names_the_board(client):
    resp = client.get("/health")
    assert resp.status_code == 200 and resp.get_json()["product"] == "conclave-board"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


def test_every_other_route_needs_a_token(client):
    assert client.get("/board").status_code == 401
    assert client.get("/board", headers=_h("falsch")).status_code == 401
    assert client.get("/auth/whoami", headers=_h(REVIEWER)).get_json() == {"role": "reviewer"}


def test_only_board_routes_exist(client):
    for path in ("/", "/conversations", "/agents", "/workspace", "/settings", "/consultations", "/static/x.js"):
        assert client.get(path, headers=_h(HUMAN)).status_code == 404, path


def test_board_flow_with_roles(client):
    assert client.post("/board/projects", json={"slug": "api", "name": "API"}, headers=_h(HUMAN)).status_code == 201
    created = client.post("/board/tasks", json={"project": "api", "title": "Erstes"}, headers=_h(AGENT))
    assert created.status_code == 201 and created.get_json()["origin"] == "agent"
    assert client.get("/board", headers=_h(AGENT)).status_code == 403            # Uebersicht nur Mensch
    assert client.post("/board/projects", json={"slug": "x", "name": "X"}, headers=_h(AGENT)).status_code == 403
    assert client.post("/board/tasks", json={"project": "api", "title": "R"}, headers=_h(REVIEWER)).status_code == 403
    nxt = client.post("/board/next", json={"project": "api"}, headers=_h(AGENT)).get_json()
    assert nxt["task"]["ref"] == "api#1" and nxt["task"]["status"] == "doing"
    moved = client.patch("/board/projects/api/tasks/1", json={"status": "review"}, headers=_h(AGENT))
    assert moved.status_code == 200
    assert client.patch("/board/projects/api/tasks/1", json={"status": "done"}, headers=_h(AGENT)).status_code == 403
    review =client.post("/board/projects/api/tasks/1/review", json={"state": "running", "comment": "laeuft"},
                         headers=_h(REVIEWER))
    assert review.status_code == 200 and review.get_json()["review"]["state"] == "running"


def test_host_check_and_content_type(client):
    assert client.get("/health", headers={"Host": "evil.example"}).status_code == 421
    resp = client.post("/board/projects", data="slug=x", headers={**_h(HUMAN),
                                                                "Content-Type": "application/x-www-form-urlencoded"})
    assert resp.status_code == 415


def test_request_size_is_limited(client):
    body = json.dumps({"slug": "big", "name": "x" * (11 * 1024 * 1024)})
    resp = client.post("/board/projects", data=body, headers={**_h(HUMAN), "Content-Type": "application/json"})
    assert resp.status_code == 413


def test_server_creates_private_secrets(tmp_path):
    config = tmp_path / "config"
    app = build_app(db_path=tmp_path / "data" / "board.db", config_dir=config)
    for name in ("secret.key", "api.token", "agent.token", "reviewer.token"):
        assert (config / name).is_file(), name
        assert file_security.foreign_access(config / name) == []
    assert (config / "api.token").read_text().startswith("cvh_")
    assert (config / "agent.token").read_text().startswith("cva_")
    if os.name != "nt":
        assert stat.S_IMODE((tmp_path / "data" / "board.db").stat().st_mode) == 0o600
    token = (config / "api.token").read_text().strip()
    assert app.test_client().get("/board", headers=_h(token)).status_code == 200


def test_board_package_runs_without_personal_and_provider_sdks(tmp_path):
    """Eigener Prozess nur mit dem Board-Paket: conclave, anthropic, openai, httpx und mcp sind gesperrt."""
    code = textwrap.dedent("""
        import importlib.abc, sys

        class Block(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path=None, target=None):
                if name.split(".")[0] in ("conclave", "anthropic", "openai", "httpx", "mcp"):
                    raise ImportError("gesperrt: " + name)
                return None

        sys.meta_path.insert(0, Block())
        from pathlib import Path
        from conclave_board.server import build_app
        tmp = Path(sys.argv[1])
        app = build_app(db_path=tmp / "board.db", config_dir=tmp / "config")
        token = (tmp / "config" / "api.token").read_text().strip()
        c = app.test_client()
        assert c.get("/health").get_json()["product"] == "conclave-board"
        assert c.post("/board/projects", json={"slug": "t1", "name": "T1"},
                      headers={"Authorization": "Bearer " + token}).status_code == 201
        loaded = sorted(n for n in sys.modules if n.split(".")[0] in ("conclave", "anthropic", "openai", "httpx"))
        assert loaded == [], loaded
        print("ok")
    """)
    env = dict(os.environ, PYTHONPATH=str(ROOT / "packages" / "board" / "src"))
    env.pop("CONCLAVE_SECRET_KEY", None)
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], env=env, capture_output=True, text=True,
                            timeout=120)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("ok")


def test_cli_help_and_version():
    env = dict(os.environ, PYTHONPATH=str(ROOT / "packages" / "board" / "src"))
    result = subprocess.run([sys.executable, "-m", "conclave_board.server", "--version"], env=env,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0 and result.stdout.startswith("conclave-board-server ")
