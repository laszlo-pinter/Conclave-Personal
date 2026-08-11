# tests/cli/test_config.py

import tomllib
from pathlib import Path

import pytest

from conclave.cli.config import ConclaveConfig, load_config
from conclave.runtime.paths import get_runtime_paths


def test_load_config_returns_defaults_when_no_file(tmp_path):
    config = load_config(config_path=tmp_path / "config.toml")

    assert config.db_path == get_runtime_paths().db_path
    assert config.participants == {}


def test_load_config_reads_db_path(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text('[conclave]\ndb_path = "/tmp/mydb.db"\n')

    config = load_config(config_path=config_file)

    assert config.db_path == Path("/tmp/mydb.db")


def test_load_config_reads_participants(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        '[conclave]\n'
        '[participants.claude1]\n'
        'provider = "anthropic"\n'
        'model = "claude-sonnet-4-20250514"\n'
        'system_prompt = "Sei präzise."\n'
        '[participants.gpt1]\n'
        'provider = "openai"\n'
        'model = "gpt-4o"\n',
        encoding="utf-8",
    )

    config = load_config(config_path=config_file)

    assert "claude1" in config.participants
    assert config.participants["claude1"]["provider"] == "anthropic"
    assert config.participants["claude1"]["model"] == "claude-sonnet-4-20250514"
    assert config.participants["claude1"]["system_prompt"] == "Sei präzise."
    assert "gpt1" in config.participants
    assert config.participants["gpt1"]["provider"] == "openai"


def test_load_config_missing_section_uses_defaults(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("[other]\nkey = 'value'\n")

    config = load_config(config_path=config_file)

    assert config.db_path == get_runtime_paths().db_path
    assert config.participants == {}


def test_conclave_config_is_dataclass():
    config = ConclaveConfig(
        db_path=Path("/tmp/test.db"),
        participants={"p1": {"provider": "anthropic", "model": "claude-sonnet-4-20250514"}},
    )
    assert config.db_path == Path("/tmp/test.db")
    assert "p1" in config.participants
