# tests/api/test_rbac_enforcement.py
#
# Rote Tests: RoleBasedAuthService.check_permission() muss in app.py
# tatsächlich aufgerufen werden.

import pytest
pytest.importorskip("flask")

from unittest.mock import MagicMock
from conclave.api.app import create_app
from conclave.cli.handler import CLIResult
from conclave.infrastructure.auth import RoleBasedAuthService


@pytest.fixture
def handler():
    h = MagicMock()
    h.list_conversations.return_value = CLIResult(success=True, message="ok", data={"conversations": []})
    h.new_conversation.return_value = CLIResult(success=True, message="ok", data={"conversation_id": "c1"})
    h.delete_conversation.return_value = CLIResult(success=True, message="ok", data={})
    h.list_agents.return_value = CLIResult(success=True, message="ok", data={"agents": []})
    return h


@pytest.fixture
def rbac_auth():
    """RoleBasedAuthService mit drei Rollen."""
    return RoleBasedAuthService({
        "viewer-token":   "viewer",
        "operator-token": "operator",
        "admin-token":    "owner",
    })


@pytest.fixture
def client(handler, rbac_auth):
    app = create_app(handler, auth_service=rbac_auth)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ── Viewer-Rolle ───────────────────────────────────────────────────────────────

class TestViewerRoleEnforcement:

    def test_viewer_can_read_conversations(self, client):
        resp = client.get("/conversations", headers={"X-API-Key": "viewer-token"})
        assert resp.status_code == 200

    def test_viewer_cannot_create_conversation(self, client):
        """Viewer hat keine POST-Rechte → 403, nicht 201."""
        resp = client.post("/conversations", headers={"X-API-Key": "viewer-token"})
        assert resp.status_code == 403

    def test_viewer_cannot_delete_conversation(self, client):
        """Viewer hat keine DELETE-Rechte → 403."""
        resp = client.delete("/conversations/c1", headers={"X-API-Key": "viewer-token"})
        assert resp.status_code == 403

    def test_viewer_can_read_agents(self, client):
        resp = client.get("/agents", headers={"X-API-Key": "viewer-token"})
        assert resp.status_code == 200

    def test_viewer_cannot_create_agent(self, client):
        resp = client.post("/agents", json={"id": "a", "name": "A", "model": "m"},
                           headers={"X-API-Key": "viewer-token"})
        assert resp.status_code == 403


# ── Operator-Rolle ─────────────────────────────────────────────────────────────

class TestOperatorRoleEnforcement:

    def test_operator_can_create_conversation(self, client):
        resp = client.post("/conversations", headers={"X-API-Key": "operator-token"})
        assert resp.status_code == 201

    def test_operator_can_read_agents(self, client):
        resp = client.get("/agents", headers={"X-API-Key": "operator-token"})
        assert resp.status_code == 200


# ── Owner-Rolle ────────────────────────────────────────────────────────────────

class TestAdminRoleEnforcement:

    def test_admin_can_read_agents(self, client):
        resp = client.get("/agents", headers={"X-API-Key": "admin-token"})
        assert resp.status_code == 200


# ── Ungültiges Token bleibt 401 ────────────────────────────────────────────────

def test_invalid_token_still_returns_401(client):
    resp = client.get("/conversations", headers={"X-API-Key": "garbage"})
    assert resp.status_code == 401
