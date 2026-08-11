# tests/infrastructure/test_auth.py

import pytest

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
