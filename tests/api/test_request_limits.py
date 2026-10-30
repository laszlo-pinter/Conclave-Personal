"""R6 (conclave#41): Body-Grenze, Laengengrenzen im Board, Freigabe fuer @read ueber die Regeln."""

import pytest

pytest.importorskip("flask")

from conclave.cli.config import ConclaveConfig  # noqa: E402

HUMAN = "cvh_mensch-token"
AGENT = "cva_agent-token"


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(tmp_path):
    from conclave.api.server import _build_app
    app, _ = _build_app(ConclaveConfig(db_path=tmp_path / "c.db", api_key=HUMAN, agent_api_key=AGENT))
    app.config["TESTING"] = True
    c = app.test_client()
    c.post("/board/projects", json={"slug": "api", "name": "API"}, headers=_bearer(HUMAN))
    return c


def test_too_large_body_is_413_with_json(client):
    conv = client.post("/conversations", json={}, headers=_bearer(HUMAN)).get_json()["conversation_id"]
    resp = client.post(f"/conversations/{conv}/messages", data="x" * (10 * 1024 * 1024 + 10),
                       headers={**_bearer(HUMAN), "Content-Type": "application/json"})
    assert resp.status_code == 413 and resp.get_json()["type"] == "RequestTooLarge"


def test_board_import_keeps_its_own_larger_limit(client):
    """12 MB Export: ueber der allgemeinen Grenze, unter der des Imports - also kein 413."""
    big = '{"projects": [], "x": "' + "y" * (12 * 1024 * 1024) + '"}'
    resp = client.post("/board/import", data=big, headers={**_bearer(HUMAN), "Content-Type": "application/json"})
    assert resp.status_code == 200, resp.get_json()


@pytest.mark.parametrize("body, field", [
    ({"title": "t" * 301}, "Titel"),
    ({"title": "T", "description": "d" * (64 * 1024 + 1)}, "Beschreibung"),
    ({"title": "T", "tags": [f"t{i}" for i in range(51)]}, "Tags"),
    ({"title": "T", "tags": ["t" * 51]}, "Tags"),
])
def test_board_field_limits_on_create_and_update(client, body, field):
    resp = client.post("/board/tasks", json={"project": "api", **body}, headers=_bearer(AGENT))
    assert resp.status_code == 400 and field in resp.get_json()["error"], resp.get_json()
    client.post("/board/tasks", json={"project": "api", "title": "ok"}, headers=_bearer(AGENT))
    update = {k: v for k, v in body.items() if k != "title" or len(v) > 1}
    resp = client.patch("/board/projects/api/tasks/1", json=update, headers=_bearer(AGENT))
    assert resp.status_code == 400, update


def test_comment_length_limit(client):
    client.post("/board/tasks", json={"project": "api", "title": "T"}, headers=_bearer(AGENT))
    resp = client.post("/board/projects/api/tasks/1/comments", json={"body": "c" * (64 * 1024 + 1)},
                       headers=_bearer(AGENT))
    assert resp.status_code == 400 and "Kommentar" in resp.get_json()["error"]


def test_import_rejects_too_long_fields(client, board_sample_export):
    board_sample_export["projects"][0]["tasks"][0]["title"] = "t" * 301
    resp = client.post("/board/import", json=board_sample_export, headers=_bearer(HUMAN))
    assert resp.status_code == 400 and resp.get_json()["type"] == "ImportFormatError"


def test_model_read_opt_in_only_for_the_human(client):
    conv = client.post("/conversations", json={}, headers=_bearer(HUMAN)).get_json()["conversation_id"]
    assert client.get(f"/conversations/{conv}/rules", headers=_bearer(HUMAN)).get_json()["model_read"] is False
    assert client.post(f"/conversations/{conv}/rules", json={"rules": "", "model_read": True},
                       headers=_bearer(AGENT)).status_code == 403
    assert client.post(f"/conversations/{conv}/rules", json={"rules": "", "model_read": "ja"},
                       headers=_bearer(HUMAN)).status_code == 400
    resp = client.post(f"/conversations/{conv}/rules", json={"rules": "kurz", "model_read": True},
                       headers=_bearer(HUMAN))
    assert resp.get_json() == {"rules": "kurz", "model_read": True}
    assert client.get(f"/conversations/{conv}/rules", headers=_bearer(HUMAN)).get_json()["model_read"] is True
    # ohne model_read bleibt die Freigabe, wie sie ist
    client.post(f"/conversations/{conv}/rules", json={"rules": "neu"}, headers=_bearer(HUMAN))
    assert client.get(f"/conversations/{conv}/rules", headers=_bearer(HUMAN)).get_json()["model_read"] is True
