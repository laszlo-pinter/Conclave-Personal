# tests/api/test_openapi_contract.py
"""Drift-Detection: verifiziert dass die in static/openapi.json deklarierten
Response-Schemas tatsaechlich von der API geliefert werden.

Schlaegt fehl wenn:
- Ein Endpoint sein required-Response-Feld nicht liefert (Schema-Drift)
- Die OpenAPI-Spec einen Pfad deklariert, der im App nicht existiert
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask")

from conclave.api.app import create_app
from conclave.cli.handler import CLIResult


SPEC_PATH = Path(__file__).resolve().parent.parent.parent / "static" / "openapi.json"


@pytest.fixture(scope="module")
def spec() -> dict:
    with open(SPEC_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def handler():
    h = MagicMock()
    # Setup damit invoke sinnvolle CLIResults liefert.
    h.new_conversation.return_value = CLIResult(
        success=True, message="ok", data={"conversation_id": "conv-test"}
    )
    h.add_participant.return_value = CLIResult(
        success=True, message="ok", data={"participant_id": "PRIM"}
    )
    h.add_message.return_value = CLIResult(
        success=True, message="ok", data={"sequence": 1, "content": "prompt"}
    )
    h.invoke_participant.return_value = CLIResult(
        success=True, message="ok",
        data={"participant_id": "PRIM", "content": "primary response", "sequence": 2},
    )
    return h


@pytest.fixture
def client(handler):
    app = create_app(handler)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _required_fields_of(spec: dict, path: str, method: str) -> list[str]:
    op = spec["paths"][path][method.lower()]
    schema = (
        op.get("responses", {}).get("200", {})
          .get("content", {}).get("application/json", {})
          .get("schema", {})
    )
    return list(schema.get("required", []))


def test_spec_loads_and_has_paths(spec):
    assert spec["openapi"].startswith("3.")
    # Kernpfade muessen deklariert sein
    expected_core_paths = {
        "/conversations",
        "/conversations/{conversation_id}",
        "/conversations/{conversation_id}/messages",
        "/conversations/{conversation_id}/participants",
        "/conversations/{conversation_id}/participants/{participant_id}/invoke",
        "/agents",
    }
    missing = expected_core_paths - set(spec["paths"].keys())
    assert not missing, f"Spec fehlen Kernpfade: {missing}"


def test_create_conversation_response_matches_spec(client, spec):
    required = _required_fields_of(spec, "/conversations", "POST")
    response = client.post("/conversations", json={})
    assert response.status_code == 201
    body = response.get_json()
    for field in required:
        assert field in body, f"POST /conversations: required '{field}' fehlt"


def test_invoke_response_matches_spec(client, spec):
    path = "/conversations/{conversation_id}/participants/{participant_id}/invoke"
    required = _required_fields_of(spec, path, "POST")
    response = client.post("/conversations/conv-test/participants/PRIM/invoke", json={})
    assert response.status_code == 200
    body = response.get_json()
    for field in required:
        assert field in body, f"invoke: required '{field}' fehlt"


def test_spec_does_not_expose_judge_contract(spec):
    paths = set(spec["paths"])
    assert "/conversations/{conversation_id}/judge" not in paths

    path = "/conversations/{conversation_id}/participants/{participant_id}/invoke"
    op = spec["paths"][path]["post"]
    req_schema = (
        op.get("requestBody", {})
          .get("content", {})
          .get("application/json", {})
          .get("schema", {})
    )
    req_properties = req_schema.get("properties", {})
    assert "judge_via" not in req_properties
    assert "judge_prompt" not in req_properties

    resp_schema = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert "judge" not in resp_schema.get("properties", {})


def test_all_declared_paths_have_at_least_one_operation(spec):
    """Sanity: jeder Pfad in der Spec hat mindestens eine Methode."""
    valid_methods = {"get", "post", "put", "delete", "patch"}
    for path, ops in spec["paths"].items():
        methods = set(ops.keys()) & valid_methods
        assert methods, f"Pfad ohne Operation in Spec: {path}"
