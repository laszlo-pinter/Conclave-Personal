# tests/cli/test_boot_validation.py

"""Production-Boot muss verweigern wenn Pflicht-TOM fehlen."""

from pathlib import Path
from unittest.mock import patch

import pytest

from conclave.cli.config import ConclaveConfig
from conclave.cli.bootstrap import validate_production_config


class TestProductionBootRefused:
    def test_fails_without_api_key(self):
        config = ConclaveConfig(mode="production")
        errors = validate_production_config(config)
        assert any("API_KEY" in e or "api_key" in e for e in errors)

    def test_fails_without_secret_key(self):
        config = ConclaveConfig(mode="production", api_key="key")
        with patch("conclave.cli.bootstrap._secret_key_available", return_value=False):
            errors = validate_production_config(config)
        assert any("secret" in e.lower() or "encrypt" in e.lower() for e in errors)

    def test_passes_with_all_requirements(self):
        config = ConclaveConfig(mode="production", api_key="my-key")
        with patch("conclave.cli.bootstrap._secret_key_available", return_value=True):
            errors = validate_production_config(config)
        assert errors == []


class TestDevelopmentBootOpen:
    def test_dev_mode_boots_without_api_key(self):
        config = ConclaveConfig(mode="development")
        errors = validate_production_config(config)
        assert errors == []

    def test_dev_mode_blocks_lan_bind_without_api_key(self):
        config = ConclaveConfig(mode="development", host="0.0.0.0", api_key="")
        errors = validate_production_config(config)
        assert any("CONCLAVE_API_KEY" in e for e in errors)

    def test_dev_mode_is_default(self):
        config = ConclaveConfig()
        assert config.mode == "development"


class TestConfigModeField:
    def test_mode_from_env(self, tmp_path):
        env = {"CONCLAVE_MODE": "production"}
        with patch.dict("os.environ", env, clear=True):
            config = ConclaveConfig.from_sources(config_path=tmp_path / "nope.toml")
        assert config.mode == "production"

    def test_mode_default_development(self, tmp_path):
        with patch.dict("os.environ", {}, clear=True):
            config = ConclaveConfig.from_sources(config_path=tmp_path / "nope.toml")
        assert config.mode == "development"
