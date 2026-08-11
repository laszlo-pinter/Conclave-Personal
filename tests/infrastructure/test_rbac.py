# tests/infrastructure/test_rbac.py

import pytest

from conclave.infrastructure.auth import RoleBasedAuthService


class TestRoleBasedAuthService:
    def test_valid_token_returns_role(self):
        svc = RoleBasedAuthService({"key-viewer": "viewer", "key-admin": "owner"})
        assert svc.validate_token("key-viewer") is True
        assert svc.get_role("key-viewer") == "viewer"

    def test_invalid_token_rejected(self):
        svc = RoleBasedAuthService({"key-viewer": "viewer"})
        assert svc.validate_token("wrong") is False

    def test_get_role_returns_none_for_invalid(self):
        svc = RoleBasedAuthService({"key-viewer": "viewer"})
        assert svc.get_role("wrong") is None

    def test_check_permission_viewer_can_read(self):
        svc = RoleBasedAuthService({"k": "viewer"})
        assert svc.check_permission("viewer", "GET", "/conversations") is True

    def test_check_permission_viewer_cannot_create(self):
        svc = RoleBasedAuthService({"k": "viewer"})
        assert svc.check_permission("viewer", "POST", "/conversations") is False

    def test_check_permission_operator_can_create(self):
        svc = RoleBasedAuthService({"k": "operator"})
        assert svc.check_permission("operator", "POST", "/conversations") is True

    def test_check_permission_operator_can_manage_agents(self):
        svc = RoleBasedAuthService({"k": "operator"})
        assert svc.check_permission("operator", "POST", "/agents") is True

    def test_check_permission_owner_can_manage_agents(self):
        svc = RoleBasedAuthService({"k": "owner"})
        assert svc.check_permission("owner", "POST", "/agents") is True

    def test_check_permission_owner_can_create_conversations(self):
        svc = RoleBasedAuthService({"k": "owner"})
        assert svc.check_permission("owner", "POST", "/conversations") is True

    def test_check_permission_key_admin_can_set_agent_key(self):
        svc = RoleBasedAuthService({"k": "key_admin"})
        assert svc.check_permission("key_admin", "PUT", "/agents/a1") is True
