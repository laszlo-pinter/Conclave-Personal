# tests/api/test_request_guards.py

"""AP 2: Token-Pflicht, Host-Allowlist (B2), CSRF-Schutz (B3), oeffentliche UI-Pfade (B12)."""

import os
import stat

import pytest
pytest.importorskip("flask")

from unittest.mock import MagicMock

from conclave.api.app import create_app, is_host_allowed, parse_allowed_hosts
from conclave.cli.config import ConclaveConfig
from conclave.cli.handler import CLIResult
from conclave.infrastructure.auth import StaticKeyAuthService
from conclave.runtime import api_token

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

# Alle POST-Endpunkte ohne JSON-Body aus B3
BODYLESS_POSTS = [
    "/conversations",
    "/agents/a1/test",
    "/conversations/c1/floor/revoke",
    "/conversations/c1/floor/invoke",
    "/conversations/c1/participants/p1/invoke",
    "/backup",
]


@pytest.fixture
def handler():
    h = MagicMock()
    ok = CLIResult(success=True, message="ok", data={})
    h.list_conversations.return_value = CLIResult(success=True, message="ok", data={"conversations": []})
    h.new_conversation.return_value = CLIResult(success=True, message="ok", data={"conversation_id": "c1"})
    h.revoke_floor.return_value = ok
    h.invoke_with_floor.return_value = ok
    h.invoke_participant.return_value = ok
    h.test_agent.return_value = {"success": True}
    return h


def _client(handler, auth=True, config=None):
    app = create_app(handler, auth_service=StaticKeyAuthService(TOKEN) if auth else None, config=config)
    app.config["TESTING"] = True
    return app.test_client()


# ── B12: UI ist mit aktivem Token ladbar ─────────────────────────────────

@pytest.mark.parametrize("path", ["/", "/health", "/api-docs", "/openapi.json", "/static/js/utils.js",
                                  "/static/vendor/purify.min.js"])
def test_public_paths_load_without_token(handler, path):
    assert _client(handler).get(path).status_code == 200


@pytest.mark.parametrize("method,path", [
    ("GET", "/conversations"), ("GET", "/settings"), ("GET", "/workspace"),
    ("POST", "/conversations"), ("DELETE", "/agents/a1"), ("PUT", "/settings"),
])
def test_api_endpoints_require_token(handler, method, path):
    resp = _client(handler).open(path, method=method, json={})
    assert resp.status_code == 401


def test_public_path_exemption_is_get_only(handler):
    assert _client(handler).post("/health", json={}).status_code in (401, 405)


# ── B2: Host-Allowlist ───────────────────────────────────────────────────

@pytest.mark.parametrize("host", ["localhost", "localhost:8000", "127.0.0.1:51234", "[::1]:8000"])
def test_loopback_hosts_are_allowed(handler, host):
    resp = _client(handler).get("/conversations", headers={**AUTH, "Host": host})
    assert resp.status_code == 200


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8000", "127.0.0.1.evil.example", "localhost.evil:8000"])
def test_foreign_host_is_rejected_even_with_valid_token(handler, host):
    resp = _client(handler).get("/conversations", headers={**AUTH, "Host": host})
    assert resp.status_code == 421
    assert resp.get_json()["type"] == "InvalidHost"


def test_foreign_host_is_rejected_for_public_paths(handler):
    assert _client(handler).get("/", headers={"Host": "evil.example"}).status_code == 421


def test_foreign_host_is_rejected_without_auth_service(handler):
    assert _client(handler, auth=False).get("/conversations", headers={"Host": "evil.example"}).status_code == 421


def test_configured_hosts_extend_loopback(handler):
    client = _client(handler, config=ConclaveConfig(allowed_hosts="conclave.lan, nas.local:9000"))
    assert client.get("/conversations", headers={**AUTH, "Host": "conclave.lan:8000"}).status_code == 200
    assert client.get("/conversations", headers={**AUTH, "Host": "nas.local:9000"}).status_code == 200
    assert client.get("/conversations", headers={**AUTH, "Host": "nas.local:8000"}).status_code == 421
    assert client.get("/conversations", headers={**AUTH, "Host": "localhost:8000"}).status_code == 200


def test_allowed_hosts_from_environment(handler, monkeypatch):
    monkeypatch.setenv("CONCLAVE_ALLOWED_HOSTS", "conclave.lan")
    assert _client(handler).get("/conversations", headers={**AUTH, "Host": "conclave.lan"}).status_code == 200


def test_host_parsing():
    allowed = parse_allowed_hosts("")
    assert is_host_allowed("LOCALHOST:8000", allowed)
    assert is_host_allowed("[::1]", allowed)
    assert not is_host_allowed("", allowed)
    assert not is_host_allowed("[::1].evil", allowed)


# ── B3: CSRF ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", BODYLESS_POSTS)
def test_simple_cross_site_posts_are_rejected(handler, path):
    resp = _client(handler).post(path, data="x", content_type="text/plain", headers=AUTH)
    assert resp.status_code == 415
    assert resp.get_json()["type"] == "UnsupportedMediaType"


@pytest.mark.parametrize("content_type", ["application/x-www-form-urlencoded", "multipart/form-data; boundary=x"])
def test_form_posts_are_rejected(handler, content_type):
    resp = _client(handler).post("/conversations", data="a=b", content_type=content_type, headers=AUTH)
    assert resp.status_code == 415


def test_post_without_body_or_header_is_rejected(handler):
    assert _client(handler).post("/conversations", headers=AUTH).status_code == 415


@pytest.mark.parametrize("path", BODYLESS_POSTS)
def test_json_posts_are_accepted(handler, path, tmp_path, monkeypatch):
    monkeypatch.setenv("CONCLAVE_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(tmp_path / "ws"))
    resp = _client(handler).post(path, json={}, headers=AUTH)
    assert resp.status_code in (200, 201)


def test_client_header_allows_post_without_json(handler):
    resp = _client(handler).post("/conversations", headers={**AUTH, "X-Conclave-Client": "cli"})
    assert resp.status_code == 201


def test_csrf_check_applies_without_auth_service(handler):
    assert _client(handler, auth=False).post("/conversations", data="x", content_type="text/plain").status_code == 415


def test_unknown_routes_keep_their_routing_error(handler):
    # 405 statt 404, weil die OPTIONS-Route fuer alle Pfade registriert ist (bestehendes Verhalten)
    resp = _client(handler, auth=False).post("/does-not-exist", data="x", content_type="text/plain")
    assert resp.status_code in (404, 405)


def test_cors_preflight_allows_client_header(handler):
    resp = _client(handler).options("/conversations", headers={"Origin": "http://localhost:8000"})
    assert "X-Conclave-Client" in resp.headers.get("Access-Control-Allow-Headers", "")


# ── Token immer Pflicht, Token-Datei ──────────────────────────────────────

def test_server_always_requires_token(monkeypatch, tmp_path):
    from conclave.api.server import _build_app
    monkeypatch.delenv("CONCLAVE_API_KEY", raising=False)
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(tmp_path / "ws"))
    app, config = _build_app(ConclaveConfig(db_path=tmp_path / "c.db", api_key=""))
    client = app.test_client()
    token = (tmp_path / "api.token").read_text(encoding="utf-8").strip()
    assert config.api_key == token
    assert client.get("/conversations").status_code == 401
    assert client.get("/conversations", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert client.get("/").status_code == 200


def test_explicit_api_key_wins_over_token_file(monkeypatch, tmp_path):
    from conclave.api.server import _build_app
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(tmp_path / "ws"))
    app, _ = _build_app(ConclaveConfig(db_path=tmp_path / "c.db", api_key="explicit"))
    assert app.test_client().get("/conversations", headers={"Authorization": "Bearer explicit"}).status_code == 200
    assert not (tmp_path / "api.token").exists()


def test_token_file_is_created_once_and_reused(tmp_path):
    path = tmp_path / "sub" / "api.token"
    first = api_token.load_or_create_token(path)
    assert len(first) >= 40
    assert api_token.load_or_create_token(path) == first


@pytest.mark.skipif(os.name == "nt", reason="POSIX-Dateirechte")
def test_token_file_is_private_on_posix(tmp_path):
    path = tmp_path / "api.token"
    api_token.load_or_create_token(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_read_token_prefers_environment(monkeypatch, tmp_path):
    path = tmp_path / "api.token"
    monkeypatch.setenv("CONCLAVE_API_TOKEN_FILE", str(path))
    monkeypatch.delenv("CONCLAVE_API_KEY", raising=False)
    assert api_token.read_token() == ""
    api_token.load_or_create_token(path)
    assert api_token.read_token() == path.read_text(encoding="utf-8").strip()
    monkeypatch.setenv("CONCLAVE_API_KEY", "from-env")
    assert api_token.read_token() == "from-env"


def test_token_path_defaults_to_config_dir(monkeypatch):
    monkeypatch.delenv("CONCLAVE_API_TOKEN_FILE", raising=False)
    from conclave.runtime.paths import get_runtime_paths
    assert api_token.token_path() == get_runtime_paths().config_dir / "api.token"
