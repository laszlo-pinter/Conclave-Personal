# tests/api/test_server_boot.py

"""Production-Boot muss verweigert werden wenn Pflicht-TOM fehlen."""

import pytest
pytest.importorskip("flask")

from unittest.mock import patch

from conclave.cli.bootstrap import validate_production_config
from conclave.cli.config import ConclaveConfig


class TestValidateProductionConfigEnforcement:
    """validate_production_config wird in server.py aufgerufen und blockiert."""

    def test_production_without_api_key_has_errors(self):
        config = ConclaveConfig(mode="production", api_key="")
        with patch("conclave.cli.bootstrap._secret_key_available", return_value=True):
            errors = validate_production_config(config)
        assert len(errors) > 0
        assert any("API_KEY" in e for e in errors)

    def test_production_without_secret_key_has_errors(self):
        config = ConclaveConfig(mode="production", api_key="my-key")
        with patch("conclave.cli.bootstrap._secret_key_available", return_value=False):
            errors = validate_production_config(config)
        assert len(errors) > 0

    def test_production_with_all_requirements_no_errors(self):
        config = ConclaveConfig(mode="production", api_key="my-key")
        with patch("conclave.cli.bootstrap._secret_key_available", return_value=True):
            errors = validate_production_config(config)
        assert errors == []

    def test_development_mode_always_passes(self):
        config = ConclaveConfig(mode="development", api_key="")
        errors = validate_production_config(config)
        assert errors == []

    def test_server_imports_validate(self):
        """server.py muss validate_production_config importieren und aufrufen."""
        import conclave.api.server as server_module
        source = open(server_module.__file__).read()
        assert "validate_production_config" in source

    def test_cli_main_imports_validate(self):
        """main.py muss validate_production_config importieren und aufrufen."""
        import conclave.cli.main as main_module
        source = open(main_module.__file__).read()
        assert "validate_production_config" in source
