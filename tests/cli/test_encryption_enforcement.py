# tests/cli/test_encryption_enforcement.py

"""Production-Modus muss Verschluesselung erzwingen."""

from unittest.mock import patch

import pytest

from conclave.cli.bootstrap import build_service
from conclave.cli.config import ConclaveConfig


def test_production_build_service_has_crypto(tmp_path):
    """build_service im Production-Modus muss CryptoService laden."""
    config = ConclaveConfig(mode="production", db_path=tmp_path / "test.db")
    service = build_service(config=config)
    # MessageRepository muss crypto haben
    assert service._message_repository._crypto is not None


def test_development_build_service_also_has_crypto(tmp_path):
    """Auch im Development-Modus wird crypto geladen (seit Welle 1)."""
    config = ConclaveConfig(mode="development", db_path=tmp_path / "test.db")
    service = build_service(config=config)
    assert service._message_repository._crypto is not None


def test_production_refuses_without_secret_key(tmp_path):
    """Production-Modus ohne Secret-Key muss fehlschlagen."""
    from conclave.cli.bootstrap import validate_production_config
    config = ConclaveConfig(mode="production", api_key="key")
    with patch("conclave.cli.bootstrap._secret_key_available", return_value=False):
        errors = validate_production_config(config)
    assert any("schluessel" in e.lower() or "secret" in e.lower() for e in errors)
