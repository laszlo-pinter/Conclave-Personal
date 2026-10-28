# tests/infrastructure/test_auth.py

import hmac

import pytest
from unittest.mock import patch

from conclave.domain.principal import Principal
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
        compare.assert_called_once_with(b"my-secret-key", b"my-secret-key")


class TestPrincipal:
    """Z1: Die Rolle ergibt sich allein aus dem Token."""

    def test_both_tokens_are_recognised(self):
        svc = StaticKeyAuthService(api_key="cvh_mensch", agent_key="cva_agent")
        assert svc.authenticate("cvh_mensch") == Principal("human")
        assert svc.authenticate("cva_agent") == Principal("agent")

    @pytest.mark.parametrize("token", [None, "", "falsch", "cvh_mensch ", "cva_agen", "cvh_menschX"])
    def test_wrong_or_missing_token_is_rejected(self, token):
        svc = StaticKeyAuthService(api_key="cvh_mensch", agent_key="cva_agent")
        assert svc.authenticate(token) is None

    def test_no_agent_access_without_agent_token(self):
        svc = StaticKeyAuthService(api_key="cvh_mensch")
        assert svc.has_agent_access is False
        assert svc.authenticate("") is None
        assert svc.authenticate("cvh_mensch").is_human

    def test_human_token_never_counts_as_agent(self):
        svc = StaticKeyAuthService(api_key="gleich", agent_key="gleich")
        assert svc.has_agent_access is False
        assert svc.authenticate("gleich") == Principal("human")

    def test_legacy_token_without_prefix_is_human(self):
        svc = StaticKeyAuthService(api_key="altes-token-ohne-praefix", agent_key="cva_agent")
        assert svc.authenticate("altes-token-ohne-praefix").role == "human"

    def test_compares_against_both_tokens_without_early_exit(self):
        svc = StaticKeyAuthService(api_key="cvh_mensch", agent_key="cva_agent")
        with patch("conclave.infrastructure.auth.hmac.compare_digest", wraps=hmac.compare_digest) as compare:
            svc.authenticate("cvh_mensch")
            svc.authenticate("falsch")
        assert compare.call_count == 4

    def test_non_ascii_token_is_rejected_not_crashing(self):
        svc = StaticKeyAuthService(api_key="cvh_mensch", agent_key="cva_agent")
        assert svc.authenticate("cvh_mönsch") is None



def test_rbac_is_removed():
    """B10: Personal-Edition hat keine Rollen; toter RBAC-Code bleibt entfernt."""
    import conclave.infrastructure.auth as auth

    assert not hasattr(auth, "RoleBasedAuthService")
    assert not hasattr(auth, "_ROLE_PERMISSIONS")
    assert not hasattr(StaticKeyAuthService, "check_permission")
