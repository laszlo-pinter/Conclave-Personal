import pytest
pytest.importorskip("flask")

from unittest.mock import MagicMock

from conclave.api.app import create_app
from conclave.cli.handler import CLIResult


@pytest.fixture
def handler():
    h = MagicMock()
    h.export_conversation.return_value = CLIResult(
        success=True,
        message="ok",
        data={"id": "conv-1", "messages": [], "participants": []},
    )
    h.token_usage.return_value = CLIResult(success=True, message="ok", data={"usage": []})
    return h


@pytest.fixture
def client(handler):
    app = create_app(handler)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestPersonalExportEndpoint:
    def test_export_returns_200(self, client):
        resp = client.get("/conversations/conv-1/export")
        assert resp.status_code == 200


class TestEnterpriseEndpointsRemoved:
    @pytest.mark.parametrize("method,path", [
        ("post", "/conversations/conv-1/consent"),
        ("delete", "/conversations/conv-1/consent"),
        ("get", "/conversations/conv-1/consent"),
        ("post", "/dpa"),
        ("get", "/dpa"),
        ("get", "/audit"),
        ("post", "/admin/purge"),
    ])
    def test_enterprise_routes_are_not_registered(self, client, method, path):
        resp = getattr(client, method)(path)
        assert resp.status_code in (404, 405)
