# tests/infrastructure/test_auth.py

import pytest
from unittest.mock import patch

from conclave.infrastructure.auth import RoleBasedAuthService, StaticKeyAuthService


class TestStaticKeyAuthService:
    def test_valid_token_returns_true(self):
        svc = StaticKeyAuthService(api_key="my-secret-key")
        assert svc.validate_token("my-secret-key") is True

    def test_invalid_token_returns_false(self):
        svc = StaticKeyAuthService(api_key="my-secret-key")
        assert svc.validate_token("wrong-key") is False

    def test_empty_token_returns_false(self):
        svc = StaticKeyAuthService(api_key="my-secret-key")
        assert svc.validate_token("") is False

    def test_none_token_returns_false(self):
        svc = StaticKeyAuthService(api_key="my-secret-key")
        assert svc.validate_token(None) is False

    def test_empty_api_key_rejects_everything(self):
        svc = StaticKeyAuthService(api_key="")
        assert svc.validate_token("anything") is False
        assert svc.validate_token("") is False

    def test_uses_constant_time_compare(self):
        svc = StaticKeyAuthService(api_key="my-secret-key")
        with patch("conclave.infrastructure.auth.hmac.compare_digest", return_value=True) as compare:
            assert svc.validate_token("my-secret-key") is True
        compare.assert_called_once_with("my-secret-key", "my-secret-key")


class TestRoleBasedAuthService:
    def test_validates_tokens_with_constant_time_compare(self):
        svc = RoleBasedAuthService({"viewer-token": "viewer", "owner-token": "owner"})
        with patch("conclave.infrastructure.auth.hmac.compare_digest", side_effect=lambda a, b: a == b) as compare:
            assert svc.validate_token("owner-token") is True
        assert compare.call_count == 2

    def test_get_role_uses_constant_time_compare(self):
        svc = RoleBasedAuthService({"viewer-token": "viewer"})
        with patch("conclave.infrastructure.auth.hmac.compare_digest", return_value=True) as compare:
            assert svc.get_role("viewer-token") == "viewer"
        compare.assert_called_once_with("viewer-token", "viewer-token")
