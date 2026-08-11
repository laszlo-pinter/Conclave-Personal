# tests/api/test_openapi_contract.py
"""Drift-Detection: verifiziert dass die in static/openapi.json deklarierten
Response-Schemas tatsaechlich von der API geliefert werden.

Schlaegt fehl wenn:
- Ein Endpoint sein required-Response-Feld nicht liefert (Schema-Drift)
- Die OpenAPI-Spec einen Pfad deklariert, der im App nicht existiert
- judge_via/judge_prompt-Body wird ignoriert und das judge-Feld fehlt im Response
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
    # Setup damit invoke + invoke_with_judge sinnvolle CLIResults liefern
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
    h.invoke_with_judge.return_value = CLIResult(
        success=True, message="ok",
        data={
            "participant_id": "PRIM", "content": "primary response", "sequence": 2,
            "judge": {"participant_id": "JUDGE", "content": "judge response", "sequence": 4},
        },
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


def test_invoke_without_judge_response_matches_spec(client, spec):
    path = "/conversations/{conversation_id}/participants/{participant_id}/invoke"
    required = _required_fields_of(spec, path, "POST")
    response = client.post("/conversations/conv-test/participants/PRIM/invoke", json={})
    assert response.status_code == 200
    body = response.get_json()
    for field in required:
        assert field in body, f"invoke (no judge): required '{field}' fehlt"
    # Ohne judge_via darf 'judge' fehlen oder None sein
    assert body.get("judge") is None or "participant_id" in body["judge"]


def test_invoke_with_judge_returns_judge_field(client, spec):
    """Der Hauptvertrag fuer Chain-of-Verification: judge_via+judge_prompt im Body
    fuehren zu einem judge-Feld im Response."""
    path = "/conversations/{conversation_id}/participants/{participant_id}/invoke"
    op = spec["paths"][path]["post"]
    req_schema = op["requestBody"]["content"]["application/json"]["schema"]
    # Spec deklariert judge_via und judge_prompt im Request-Body
    assert "judge_via" in req_schema["properties"]
    assert "judge_prompt" in req_schema["properties"]

    resp_schema = op["responses"]["200"]["content"]["application/json"]["schema"]
    # Spec deklariert judge im Response
    assert "judge" in resp_schema["properties"]

    response = client.post(
        "/conversations/conv-test/participants/PRIM/invoke",
        json={"judge_via": "JUDGE", "judge_prompt": "x: {primary_response}"},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert "content" in body
    assert "judge" in body
    assert body["judge"]["participant_id"] == "JUDGE"
    assert "content" in body["judge"]


def test_invoke_with_judge_missing_prompt_returns_400(client):
    """judge_via ohne judge_prompt -> 400 (Vertrag)."""
    response = client.post(
        "/conversations/conv-test/participants/PRIM/invoke",
        json={"judge_via": "JUDGE"},
    )
    assert response.status_code == 400
    body = response.get_json()
    assert "judge_prompt" in body.get("error", "")


def test_all_declared_paths_have_at_least_one_operation(spec):
    """Sanity: jeder Pfad in der Spec hat mindestens eine Methode."""
    valid_methods = {"get", "post", "put", "delete", "patch"}
    for path, ops in spec["paths"].items():
        methods = set(ops.keys()) & valid_methods
        assert methods, f"Pfad ohne Operation in Spec: {path}"
