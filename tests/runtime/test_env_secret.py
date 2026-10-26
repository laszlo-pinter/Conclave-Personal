"""Secrets aus Umgebungsvariablen: Anfuehrungszeichen und Leerzeichen werden entfernt."""

import logging

import pytest

from conclave.runtime import env as env_module
from conclave.runtime.env import clean_secret, env_secret


@pytest.mark.parametrize("raw,expected", [
    ("sk-ant-123", "sk-ant-123"),
    ('"sk-ant-123"', "sk-ant-123"),
    ("'sk-ant-123'", "sk-ant-123"),
    ('  "sk-ant-123"  ', "sk-ant-123"),
    ("sk-ant-123\r\n", "sk-ant-123"),
    ('"\'sk\'"', "sk"),
    ('"sk-ant-123', '"sk-ant-123'),   # unpaarig: unveraendert lassen
    ('sk"in"mitte', 'sk"in"mitte'),
    ('""', ""),
    ("", ""),
])
def test_clean_secret(raw, expected):
    assert clean_secret(raw) == expected


def test_env_secret_cleans_and_warns_once_without_value(monkeypatch, caplog):
    monkeypatch.setattr(env_module, "_warned", set())
    monkeypatch.setenv("TEST_PROVIDER_KEY", '"sk-geheim"')
    with caplog.at_level(logging.WARNING, logger="conclave.runtime.env"):
        assert env_secret("TEST_PROVIDER_KEY") == "sk-geheim"
        assert env_secret("TEST_PROVIDER_KEY") == "sk-geheim"
    warnings = [r for r in caplog.records if "TEST_PROVIDER_KEY" in r.getMessage()]
    assert len(warnings) == 1
    assert "sk-geheim" not in caplog.text


def test_env_secret_default_and_clean_values(monkeypatch, caplog):
    monkeypatch.delenv("TEST_MISSING_KEY", raising=False)
    assert env_secret("TEST_MISSING_KEY") == ""
    assert env_secret("TEST_MISSING_KEY", "x") == "x"
    monkeypatch.setenv("TEST_CLEAN_KEY", "sk-ok")
    with caplog.at_level(logging.WARNING, logger="conclave.runtime.env"):
        assert env_secret("TEST_CLEAN_KEY") == "sk-ok"
    assert caplog.records == []


def test_provider_keys_from_config_are_cleaned(monkeypatch, tmp_path):
    from conclave.cli.config import ConclaveConfig
    monkeypatch.setenv("ANTHROPIC_API_KEY", '"sk-ant-x"')
    monkeypatch.setenv("OPENAI_API_KEY", " 'sk-proj-y' ")
    monkeypatch.setenv("CONCLAVE_API_KEY", '"token"')
    config = ConclaveConfig.from_sources(tmp_path / "missing.toml")
    assert config.anthropic_api_key == "sk-ant-x"
    assert config.openai_api_key == "sk-proj-y"
    assert config.api_key == "token"


def test_preset_fallback_keys_are_cleaned(monkeypatch, agent_service):
    """DeepSeek/DashScope-Keys kommen ueber api_key_env des Presets."""
    from conclave.cli.handler import CLIHandler
    from conclave.domain.agent import Agent
    monkeypatch.setenv("DEEPSEEK_API_KEY", '"sk-deep"')
    handler = CLIHandler(None, agent_service=agent_service)
    agent = Agent(id="ds", name="DeepSeek", provider="deepseek", model="deepseek-chat", preset="deepseek")
    assert handler._fallback_key_for_agent(agent) == "sk-deep"


def test_quoted_secret_key_still_works(monkeypatch, tmp_path):
    from cryptography.fernet import Fernet
    from conclave.infrastructure.crypto import CryptoService
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("CONCLAVE_SECRET_KEY", f'"{key}"')
    crypto = CryptoService.load_or_generate(tmp_path / "unused.key")
    assert crypto.decrypt(crypto.encrypt("x")) == "x"
