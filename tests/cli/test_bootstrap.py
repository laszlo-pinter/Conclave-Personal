# tests/cli/test_bootstrap.py

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from conclave.cli.bootstrap import build_agent_service, build_registry, build_service
from conclave.cli.config import ConclaveConfig
from conclave.domain.agent import Agent


def test_build_service_creates_db(tmp_path):
    config = ConclaveConfig(db_path=tmp_path / "test.db")
    service = build_service(config=config)
    assert (tmp_path / "test.db").exists()


def test_build_service_initializes_schema(tmp_path):
    config = ConclaveConfig(db_path=tmp_path / "test.db")
    service = build_service(config=config)
    assert service.create_conversation().id is not None


def test_build_agent_service_creates_db(tmp_path):
    config = ConclaveConfig(db_path=tmp_path / "test.db")
    svc = build_agent_service(config=config)
    assert svc.list_agents() == []


def test_build_agent_service_migrates_config_agents(tmp_path):
    config = ConclaveConfig(
        db_path=tmp_path / "test.db",
        participants={
            "claude1": {"provider": "anthropic", "model": "claude-sonnet-4-20250514",
                        "name": "Claude", "system_prompt": "Sei präzise."},
        },
    )
    svc = build_agent_service(config=config)
    agents = svc.list_agents()
    assert len(agents) == 1
    assert agents[0].id == "claude1"
    assert agents[0].system_prompt == "Sei präzise."


def test_build_agent_service_does_not_overwrite_existing(tmp_path):
    config = ConclaveConfig(
        db_path=tmp_path / "test.db",
        participants={"claude1": {"provider": "anthropic", "model": "m", "name": "Config-Name"}},
    )
    svc = build_agent_service(config=config)
    # Manually update agent in DB
    svc.update_agent(Agent(id="claude1", name="DB-Name", provider="anthropic", model="m"))
    # Run migration again
    from conclave.cli.bootstrap import _migrate_config_agents
    _migrate_config_agents(svc, config)
    # DB name should win
    assert svc.get_agent("claude1").name == "DB-Name"


def test_build_registry_returns_empty_registry_without_keys(tmp_path):
    """build_registry liefert jetzt immer eine Registry (mit Lazy-Builder),
    auch ohne API-Keys. Ohne registrierte Agents/Keys ist sie effektiv leer."""
    config = ConclaveConfig(db_path=tmp_path / "test.db")
    service = build_service(config=config)
    agent_service = build_agent_service(config=config)
    with patch.dict("os.environ", {}, clear=True):
        result = build_registry(service, agent_service=agent_service, config=config)
    assert result is not None
    # Keine Adapter eager registriert
    assert len(result._adapters) == 0


def test_build_registry_uses_db_agents(tmp_path):
    config = ConclaveConfig(db_path=tmp_path / "test.db", anthropic_api_key="sk-test")
    service = build_service(config=config)
    agent_svc = build_agent_service(config=config)
    agent_svc.create_agent(
        Agent(id="claude1", name="Claude", provider="anthropic", model="claude-sonnet-4-20250514")
    )
    from unittest.mock import MagicMock
    fake_adapter = MagicMock()
    with patch("conclave.cli.bootstrap._make_adapter", return_value=fake_adapter):
        registry = build_registry(service, agent_service=agent_svc, config=config)
    assert registry is not None


def test_build_registry_uses_agent_api_key_from_db(tmp_path):
    """API-Key kommt aus dem Agent-Objekt in der DB, nicht aus Env-Variablen."""
    from cryptography.fernet import Fernet
    from conclave.infrastructure.crypto import CryptoService

    crypto = CryptoService(Fernet.generate_key())
    config = ConclaveConfig(db_path=tmp_path / "test.db")
    service = build_service(config=config)
    agent_svc = build_agent_service(config=config, crypto=crypto)
    agent_svc.create_agent(
        Agent(id="gpt1", name="GPT", provider="openai",
              model="gpt-4o", api_key="sk-openai-secret")
    )
    fake_adapter = MagicMock()
    # Keine Env-Variablen gesetzt – Key muss aus DB kommen
    with patch.dict("os.environ", {}, clear=True):
        with patch("conclave.cli.bootstrap._make_adapter", return_value=fake_adapter) as mock_make:
            registry = build_registry(service, agent_service=agent_svc, config=config)

    assert registry is not None
    # _make_adapter bekommt jetzt Agent-Objekt + api_key
    call_args = mock_make.call_args
    agent_arg = call_args[0][0]
    assert agent_arg.provider == "openai"
    assert call_args[1]["api_key"] == "sk-openai-secret"
