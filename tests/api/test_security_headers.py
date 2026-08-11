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
