import pytest
pytest.importorskip("flask")

from unittest.mock import MagicMock

from conclave.api.app import create_app
from conclave.cli.handler import CLIResult


@pytest.fixture
def handler():
    h = MagicMock()
    h.list_runs.return_value = CLIResult(
        success=True,
        message="ok",
        data={"runs": [{
            "id": "run-1",
            "conversation_id": "conv-1",
            "kind": "invoke",
            "participants": ["agent-a"],
            "started_at": "2026-08-11T10:00:00+00:00",
            "finished_at": "2026-08-11T10:00:01+00:00",
            "status": "succeeded",
            "error": None,
            "usage": {"provider": "test", "model": "m", "total_tokens": 8},
        }]},
    )
    h.get_run.return_value = CLIResult(
        success=True,
        message="ok",
        data={"id": "run-1", "conversation_id": "conv-1"},
    )
    return h


@pytest.fixture
def client(handler):
    app = create_app(handler)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_get_runs_returns_runs(client, handler):
    resp = client.get("/runs?conversation_id=conv-1&limit=10")

    assert resp.status_code == 200
    assert resp.get_json()["runs"][0]["id"] == "run-1"
    handler.list_runs.assert_called_once_with(conversation_id="conv-1", limit=10)


def test_get_run_returns_run(client, handler):
    resp = client.get("/runs/run-1")

    assert resp.status_code == 200
    assert resp.get_json()["id"] == "run-1"


def test_get_run_not_found_returns_404(client, handler):
    handler.get_run.return_value = CLIResult(success=False, message="nicht gefunden")

    resp = client.get("/runs/missing")

    assert resp.status_code == 404
