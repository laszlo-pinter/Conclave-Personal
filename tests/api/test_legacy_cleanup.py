# tests/api/test_legacy_cleanup.py

"""AP 6: Altlasten entfernt (B7), Schluesselaufloesung einheitlich (B8), Debug nur lokal (B9)."""

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest
pytest.importorskip("flask")

from conclave.api.app import create_app
from conclave.cli.bootstrap import validate_production_config
from conclave.cli.config import ConclaveConfig


def test_guard_notify_endpoint_is_removed():
    client = create_app(MagicMock()).test_client()
    assert client.post("/guard/notify", json={"x": 1}).status_code in (404, 405)
    assert not any("guard" in rule.rule for rule in client.application.url_map.iter_rules())


def test_guard_is_not_in_openapi():
    from conclave.runtime.assets import get_asset_root
    spec = (get_asset_root() / "static" / "openapi.json").read_text(encoding="utf-8")
    assert "/guard/notify" not in spec
    assert "GUARD_URL" not in spec


@pytest.mark.parametrize("config,expected", [
    (ConclaveConfig(debug=True, host="127.0.0.1"), False),
    (ConclaveConfig(debug=True, host="0.0.0.0", api_key="k", allowed_hosts="lan"), True),
    (ConclaveConfig(debug=True, mode="production", api_key="k"), True),
    (ConclaveConfig(debug=False, host="0.0.0.0", api_key="k", allowed_hosts="lan"), False),
])
def test_debug_is_only_allowed_locally_in_development(config, expected):
    with patch("conclave.cli.bootstrap._secret_key_available", return_value=True):
        errors = validate_production_config(config)
    assert any("CONCLAVE_DEBUG" in e for e in errors) is expected


def test_postgres_uses_same_secret_key_resolution_as_sqlite(monkeypatch):
    """B8: kein fest verdrahtetes ~/.conclave/secret.key mehr."""
    import conclave.api.server as server

    fake_psycopg2 = ModuleType("psycopg2")
    fake_psycopg2.connect = MagicMock(return_value=MagicMock())
    monkeypatch.setitem(sys.modules, "psycopg2", fake_psycopg2)
    crypto = MagicMock()
    with patch("conclave.infrastructure.postgres.schema.initialize_schema"), \
         patch("conclave.cli.bootstrap._load_crypto", return_value=crypto) as load_crypto, \
         patch("conclave.infrastructure.crypto.CryptoService.load_or_generate") as hardcoded:
        server._build_postgres(ConclaveConfig(db_provider="postgres", db_dsn="dbname=x"))
    load_crypto.assert_called_once_with()
    hardcoded.assert_not_called()
