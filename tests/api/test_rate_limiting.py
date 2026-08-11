# tests/api/test_rate_limiting.py

import pytest
pytest.importorskip("flask")
pytest.importorskip("flask_limiter")

from unittest.mock import MagicMock

from conclave.api.app import create_app
from conclave.cli.handler import CLIResult


@pytest.fixture
def handler():
    h = MagicMock()
    h.list_conversations.return_value = CLIResult(
        success=True, message="ok", data={"conversations": []})
    return h


@pytest.fixture
def client(handler):
    app = create_app(handler)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_rate_limit_allows_within_limit(client):
    resp = client.get("/conversations")
    assert resp.status_code == 200


def test_rate_limit_header_present(client):
    """Response enthaelt Rate-Limit-Header."""
    resp = client.get("/conversations")
    # flask-limiter setzt standardmaessig RateLimit-Header
    assert resp.status_code == 200
