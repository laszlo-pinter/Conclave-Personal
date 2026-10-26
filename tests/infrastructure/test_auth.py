# tests/infrastructure/test_auth.py

import pytest
from unittest.mock import patch

from conclave.infrastructure.auth import StaticKeyAuthService


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



def test_rbac_is_removed():
    """B10: Personal-Edition hat keine Rollen; toter RBAC-Code bleibt entfernt."""
    import conclave.infrastructure.auth as auth

    assert not hasattr(auth, "RoleBasedAuthService")
    assert not hasattr(auth, "_ROLE_PERMISSIONS")
    assert not hasattr(StaticKeyAuthService, "check_permission")
