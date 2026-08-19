# tests/api/test_orchestrate_parallel_api.py

import json

import pytest
pytest.importorskip("flask")

from unittest.mock import MagicMock

from conclave.api.app import create_app
from conclave.cli.handler import CLIResult


@pytest.fixture
def handler():
    h = MagicMock()
    h.orchestrate_parallel.return_value = CLIResult(
        success=True,
        message="3 Antwort(en) erhalten.",
        data={
            "responses": [
                {"participant_id": "a", "content": "AA", "sequence": 2},
                {"participant_id": "b", "content": "BB", "sequence": 3},
                {"participant_id": "c", "content": "CC", "sequence": 4},
            ]
        },
    )
    return h


@pytest.fixture
def client(handler):
    app = create_app(handler)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_orchestrate_parallel_returns_200(client):
    resp = client.post(
        "/conversations/conv-1/orchestrate-parallel",
        json={"groups": [["a", "b"], ["c"]]},
    )
    assert resp.status_code == 200


def test_orchestrate_parallel_returns_responses(client):
    resp = client.post(
        "/conversations/conv-1/orchestrate-parallel",
        json={"groups": [["a", "b"], ["c"]]},
    )
    body = json.loads(resp.data)
    assert len(body["responses"]) == 3


def test_orchestrate_parallel_passes_groups_to_handler(client, handler):
    client.post(
        "/conversations/conv-1/orchestrate-parallel",
        json={"groups": [["a", "b"], ["c"]]},
    )
    handler.orchestrate_parallel.assert_called_once_with(
        "conv-1", [["a", "b"], ["c"]]
    )


def test_orchestrate_parallel_missing_groups_returns_400(client):
    resp = client.post(
        "/conversations/conv-1/orchestrate-parallel",
        json={},
    )
    assert resp.status_code == 400


def test_orchestrate_parallel_invalid_groups_returns_400(client):
    resp = client.post(
        "/conversations/conv-1/orchestrate-parallel",
        json={"groups": "not-a-list"},
    )
    assert resp.status_code == 400


def test_orchestrate_parallel_empty_group_returns_400(client):
    resp = client.post(
        "/conversations/conv-1/orchestrate-parallel",
        json={"groups": [["a"], []]},
    )
    assert resp.status_code == 400


def test_orchestrate_parallel_empty_participant_returns_400(client):
    resp = client.post(
        "/conversations/conv-1/orchestrate-parallel",
        json={"groups": [["a", " "]]},
    )
    assert resp.status_code == 400


def test_orchestrate_parallel_failure_returns_502(client, handler):
    handler.orchestrate_parallel.return_value = CLIResult(
        success=False, message="Fehler", data={}
    )
    resp = client.post(
        "/conversations/conv-1/orchestrate-parallel",
        json={"groups": [["a"]]},
    )
    assert resp.status_code == 502
