# tests/api/test_security_headers.py

import pytest
pytest.importorskip("flask")

from unittest.mock import MagicMock

from conclave.api.app import create_app
from conclave.cli.handler import CLIResult


@pytest.fixture
def handler():
    h = MagicMock()
    h.list_conversations.return_value = CLIResult(
        success=True, message="ok", data={"conversations": []},
    )
    return h


@pytest.fixture
def client(handler):
    app = create_app(handler)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_x_content_type_options_present(client):
    resp = client.get("/conversations")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"


def test_x_frame_options_present(client):
    resp = client.get("/conversations")
    assert resp.headers.get("X-Frame-Options") == "DENY"


def test_content_type_is_json(client):
    resp = client.get("/conversations")
    assert "application/json" in resp.content_type


# ── AP 4 / B5: Content-Security-Policy ────────────────────────────────────

def _csp(resp) -> dict:
    directives = {}
    for part in resp.headers.get("Content-Security-Policy", "").split(";"):
        name, *values = part.split()
        directives[name] = values
    return directives


@pytest.mark.parametrize("path", ["/conversations", "/", "/api-docs", "/health"])
def test_csp_present_on_all_responses(client, path):
    csp = _csp(client.get(path))
    assert csp["default-src"] == ["'self'"]
    assert csp["script-src"] == ["'self'"]
    assert csp["style-src"] == ["'self'"]
    assert csp["object-src"] == ["'none'"]
    assert csp["base-uri"] == ["'none'"]
    assert csp["frame-ancestors"] == ["'none'"]
    assert csp["connect-src"] == ["'self'"]
    assert csp["font-src"] == ["'self'"]
    assert csp["img-src"] == ["'self'", "data:"]


def test_csp_never_allows_inline_or_eval_scripts(client):
    header = client.get("/").headers["Content-Security-Policy"]
    script = _csp(client.get("/"))["script-src"]
    assert "'unsafe-inline'" not in script
    assert "'unsafe-eval'" not in header
    # Inline nur fuer style-Attribute, nie fuer <style>-Elemente
    assert _csp(client.get("/"))["style-src-attr"] == ["'unsafe-inline'"]


def test_referrer_and_permissions_policy(client):
    resp = client.get("/")
    assert resp.headers.get("Referrer-Policy") == "no-referrer"
    policy = resp.headers.get("Permissions-Policy", "")
    assert "microphone=(self)" in policy
    assert "camera=()" in policy
    assert "geolocation=()" in policy


def test_api_docs_uses_local_swagger_without_inline_script(client):
    html = client.get("/api-docs").get_data(as_text=True)
    assert "https://" not in html and "http://" not in html
    assert "/static/vendor/swagger-ui/swagger-ui-bundle.js" in html
    assert "/static/js/swagger-init.js" in html
    assert "<script>" not in html
