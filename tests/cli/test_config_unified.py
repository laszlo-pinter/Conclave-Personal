# tests/cli/test_config_unified.py

from pathlib import Path
from unittest.mock import patch

import pytest

from conclave.cli.config import ConclaveConfig, load_config
from conclave.runtime.paths import get_runtime_paths


class TestFromSources:
    """Tests für ConclaveConfig.from_sources() — vereinheitlicht TOML + Env-Vars."""

    def test_returns_defaults_without_toml_or_env(self, tmp_path):
        with patch.dict("os.environ", {}, clear=True):
            config = ConclaveConfig.from_sources(config_path=tmp_path / "nope.toml")

        assert config.db_provider == "sqlite"
        assert config.db_path == get_runtime_paths().db_path
        assert config.host == "127.0.0.1"
        assert config.port == 8000
        assert config.debug is False
        assert config.log_level == "INFO"

    def test_loads_toml_values(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            '[database]\n'
            'provider = "postgres"\n'
            'dsn = "postgresql://localhost/conclave"\n'
        )
        with patch.dict("os.environ", {}, clear=True):
            config = ConclaveConfig.from_sources(config_path=toml_file)

        assert config.db_provider == "postgres"
        assert config.db_dsn == "postgresql://localhost/conclave"

    def test_env_var_overrides_toml_provider(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text('[database]\nprovider = "sqlite"\n')
        env = {"CONCLAVE_DB_PROVIDER": "postgres", "CONCLAVE_DB_DSN": "postgresql://x"}
        with patch.dict("os.environ", env, clear=True):
            config = ConclaveConfig.from_sources(config_path=toml_file)

        assert config.db_provider == "postgres"
        assert config.db_dsn == "postgresql://x"

    def test_env_var_overrides_host_and_port(self, tmp_path):
        env = {"CONCLAVE_HOST": "0.0.0.0", "CONCLAVE_PORT": "9000"}
        with patch.dict("os.environ", env, clear=True):
            config = ConclaveConfig.from_sources(config_path=tmp_path / "nope.toml")

        assert config.host == "0.0.0.0"
        assert config.port == 9000

    def test_env_var_debug_true(self, tmp_path):
        env = {"CONCLAVE_DEBUG": "true"}
        with patch.dict("os.environ", env, clear=True):
            config = ConclaveConfig.from_sources(config_path=tmp_path / "nope.toml")

        assert config.debug is True

    def test_env_var_debug_1(self, tmp_path):
        env = {"CONCLAVE_DEBUG": "1"}
        with patch.dict("os.environ", env, clear=True):
            config = ConclaveConfig.from_sources(config_path=tmp_path / "nope.toml")

        assert config.debug is True

    def test_env_var_log_level(self, tmp_path):
        env = {"CONCLAVE_LOG_LEVEL": "DEBUG"}
        with patch.dict("os.environ", env, clear=True):
            config = ConclaveConfig.from_sources(config_path=tmp_path / "nope.toml")

        assert config.log_level == "DEBUG"

    def test_api_keys_from_env(self, tmp_path):
        env = {
            "ANTHROPIC_API_KEY": "sk-ant-xxx",
            "OPENAI_API_KEY": "sk-oai-xxx",
        }
        with patch.dict("os.environ", env, clear=True):
            config = ConclaveConfig.from_sources(config_path=tmp_path / "nope.toml")

        assert config.anthropic_api_key == "sk-ant-xxx"
        assert config.openai_api_key == "sk-oai-xxx"

    def test_api_keys_default_empty(self, tmp_path):
        with patch.dict("os.environ", {}, clear=True):
            config = ConclaveConfig.from_sources(config_path=tmp_path / "nope.toml")

        assert config.anthropic_api_key == ""
        assert config.openai_api_key == ""

    def test_missing_toml_plus_env_vars_yields_valid_config(self, tmp_path):
        env = {
            "CONCLAVE_DB_PROVIDER": "postgres",
            "CONCLAVE_DB_DSN": "postgresql://localhost/test",
            "CONCLAVE_HOST": "0.0.0.0",
            "CONCLAVE_PORT": "5000",
        }
        with patch.dict("os.environ", env, clear=True):
            config = ConclaveConfig.from_sources(config_path=tmp_path / "missing.toml")

        assert config.db_provider == "postgres"
        assert config.db_dsn == "postgresql://localhost/test"
        assert config.host == "0.0.0.0"
        assert config.port == 5000

    def test_toml_db_path_respected(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text('[database]\npath = "/custom/db.sqlite"\n')
        with patch.dict("os.environ", {}, clear=True):
            config = ConclaveConfig.from_sources(config_path=toml_file)

        assert config.db_path == Path("/custom/db.sqlite")

    def test_env_var_db_path_overrides_toml(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text('[database]\npath = "/toml/db.sqlite"\n')
        env = {"CONCLAVE_DB_PATH": "/env/db.sqlite"}
        with patch.dict("os.environ", env, clear=True):
            config = ConclaveConfig.from_sources(config_path=toml_file)

        assert config.db_path == Path("/env/db.sqlite")

    def test_participants_from_toml(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            '[participants.claude]\n'
            'provider = "anthropic"\n'
            'model = "claude-sonnet-4-20250514"\n'
        )
        with patch.dict("os.environ", {}, clear=True):
            config = ConclaveConfig.from_sources(config_path=toml_file)

        assert "claude" in config.participants
        assert config.participants["claude"]["provider"] == "anthropic"


class TestLoadConfigBackwardsCompat:
    """load_config() muss weiterhin funktionieren — Rückwärtskompatibilität."""

    def test_load_config_still_works(self, tmp_path):
        config = load_config(config_path=tmp_path / "config.toml")
        assert isinstance(config, ConclaveConfig)
        assert config.db_provider == "sqlite"

    def test_load_config_reads_participants(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            '[participants.gpt1]\nprovider = "openai"\nmodel = "gpt-4o"\n'
        )
        config = load_config(config_path=toml_file)
        assert "gpt1" in config.participants
