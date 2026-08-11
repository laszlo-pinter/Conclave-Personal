# src/conclave/cli/bootstrap.py

import os
import sqlite3
from pathlib import Path

from conclave.application.adapter_registry import AdapterRegistry
from conclave.application.agent_service import AgentService
from conclave.application.conversation_flow import ConversationFlowService
from conclave.cli.config import ConclaveConfig, load_config
from conclave.domain.agent import Agent
from conclave.infrastructure.crypto import CryptoService
from conclave.infrastructure.sqlite.agent_repository import SQLiteAgentRepository
from conclave.infrastructure.sqlite.conversation_repository import SQLiteConversationRepository
from conclave.infrastructure.sqlite.message_repository import SQLiteMessageRepository
from conclave.infrastructure.sqlite.participant_repository import SQLiteParticipantRepository
from conclave.infrastructure.sqlite.run_repository import SQLiteRunRepository
from conclave.infrastructure.sqlite.schema import initialize_schema
from conclave.runtime.paths import get_runtime_paths

DEFAULT_KEY_PATH = get_runtime_paths().secret_key_path


def _default_key_path() -> Path:
    """Ermittelt den Runtime-Key-Pfad anhand der aktuellen Umgebung."""
    return get_runtime_paths().secret_key_path


def _load_crypto(key_path: Path | None = None) -> CryptoService:
    """Lädt CryptoService – Key aus CONCLAVE_SECRET_KEY (Env) oder Datei."""
    return CryptoService.load_or_generate(key_path or _default_key_path())


def _secret_key_available(key_path: Path | None = None) -> bool:
    """Prueft ob ein Verschluesselungsschluessel verfuegbar ist."""
    if os.environ.get("CONCLAVE_SECRET_KEY"):
        return True
    return (key_path or _default_key_path()).exists()


def validate_production_config(config: ConclaveConfig) -> list[str]:
    """Gibt Fehlerliste zurueck. Leer = Production-Boot erlaubt."""
    if config.mode != "production":
        return []

    errors: list[str] = []
    if not config.api_key:
        errors.append("CONCLAVE_API_KEY ist erforderlich im Production-Modus")
    if not _secret_key_available():
        errors.append("Verschluesselungsschluessel fehlt (CONCLAVE_SECRET_KEY oder CONCLAVE_SECRET_KEY_FILE)")
    return errors


def build_unit_of_work(config: ConclaveConfig) -> object:
    """Provider-Factory: gibt SQLiteUnitOfWork oder PostgresUnitOfWork zurück."""
    if config.db_provider == "postgres":
        from conclave.infrastructure.postgres.unit_of_work import PostgresUnitOfWork
        return PostgresUnitOfWork(dsn=config.db_dsn)
    else:
        from conclave.infrastructure.sqlite.unit_of_work import SQLiteUnitOfWork
        config.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(config.db_path))
        initialize_schema(connection)
        return SQLiteUnitOfWork(connection)


def build_service(
    db_path: Path | None = None,
    config: ConclaveConfig | None = None,
    crypto: CryptoService | None = None,
    connection=None,
) -> ConversationFlowService:
    if config is None:
        config = load_config()
    if connection is None:
        resolved_path = db_path or config.db_path
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(resolved_path))
        initialize_schema(connection)

    if crypto is None:
        crypto = _load_crypto()

    service = ConversationFlowService(
        conversation_repository=SQLiteConversationRepository(connection),
        message_repository=SQLiteMessageRepository(connection, crypto=crypto),
        participant_repository=SQLiteParticipantRepository(connection),
    )
    service.set_run_repository(SQLiteRunRepository(connection))
    return service


def build_agent_service(
    db_path: Path | None = None,
    config: ConclaveConfig | None = None,
    crypto: CryptoService | None = None,
    connection=None,
) -> AgentService:
    """Erstellt den AgentService und migriert Agenten aus config.toml (einmalig)."""
    if config is None:
        config = load_config()
    if connection is None:
        resolved_path = db_path or config.db_path
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(resolved_path))
        initialize_schema(connection)

    if crypto is None:
        crypto = _load_crypto()

    repo = SQLiteAgentRepository(connection, crypto)
    svc = AgentService(repo)

    _migrate_config_agents(svc, config)

    return svc


def _migrate_config_agents(svc: AgentService, config: ConclaveConfig) -> None:
    """Überträgt Agenten aus config.toml in die DB, falls sie noch nicht existieren."""
    for pid, settings in config.participants.items():
        if svc._repo.get(pid) is not None:
            continue
        try:
            agent = Agent(
                id=pid,
                name=settings.get("name", pid),
                provider=settings.get("provider", "anthropic"),
                model=settings.get("model", ""),
                system_prompt=settings.get("system_prompt", ""),
                # api_key kommt nicht mehr aus config.toml
            )
            svc.upsert_agent(agent)
        except (ValueError, Exception):
            pass


def _build_adapter_for_agent(agent, config: ConclaveConfig):
    """Baut einen ResilientAdapter fuer einen einzelnen Agent."""
    from conclave.infrastructure.universal.resilient import ResilientAdapter

    api_key = agent.api_key or {
        "anthropic": config.anthropic_api_key,
        "openai": config.openai_api_key,
        "openai-responses": config.openai_api_key,
        "gemini": config.gemini_api_key,
    }.get(agent.provider, "")
    if not api_key and agent.provider not in ("ollama",) and not agent.preset:
        return None
    adapter = _make_adapter(agent, api_key=api_key)
    if adapter:
        return ResilientAdapter(adapter)
    return None


def build_registry(
    service: ConversationFlowService,
    agent_service: AgentService | None = None,
    config: ConclaveConfig | None = None,
) -> AdapterRegistry | None:
    """Baut AdapterRegistry mit Lazy-Builder.

    Adapter werden bei Bedarf aus der DB gebaut und gecacht.
    Beim Start werden vorhandene Agents eager geladen.
    """
    if config is None:
        config = load_config()

    registry = AdapterRegistry()

    # Lazy Builder: baut Adapter on-demand wenn nicht im Cache
    if agent_service:
        def _lazy_builder(participant_id: str):
            agent = agent_service.get_agent(participant_id)
            if agent is None:
                return None
            return _build_adapter_for_agent(agent, config)

        registry.set_builder(_lazy_builder)

        # Eager: vorhandene Agents beim Start laden
        for agent in agent_service.list_agents():
            adapter = _build_adapter_for_agent(agent, config)
            if adapter:
                registry.register(agent.id, adapter)

    service.set_adapter_registry(registry)
    return registry


def _make_adapter(agent_or_provider, api_key: str = "", model: str = "", system_prompt: str | None = None):
    """Erstellt einen Adapter fuer einen Agenten.

    Args:
        agent_or_provider: Agent-Objekt oder Provider-String (rueckwaertskompatibel).
        api_key: API-Key (Fallback wenn Agent keinen hat).
    """
    from conclave.domain.agent import Agent

    if isinstance(agent_or_provider, Agent):
        agent = agent_or_provider
        provider = agent.provider
        model = agent.model
        system_prompt = agent.system_prompt or None
        key = api_key or agent.api_key
    else:
        # Rueckwaertskompatibel: String als Provider
        provider = agent_or_provider
        key = api_key
        agent = None

    # Universal: Agent hat preset oder api_url → UniversalAdapter
    if agent and (agent.preset or agent.api_url):
        return _make_universal_adapter(agent, key)

    # Native: anthropic/openai ohne preset → optimierte Adapter
    try:
        if provider == "anthropic":
            from conclave.infrastructure.anthropic.adapter import AnthropicAdapter
            return AnthropicAdapter(api_key=key, model=model, system_prompt=system_prompt)
        elif provider == "openai":
            from conclave.infrastructure.openai.adapter import OpenAIAdapter
            return OpenAIAdapter(api_key=key, model=model, system_prompt=system_prompt)
    except ImportError:
        pass

    # Fallback: Unbekannter Provider ohne Config → None
    return None


def _make_universal_adapter(agent, api_key: str):
    """Erstellt einen UniversalAdapter aus Agent + Preset."""
    from conclave.infrastructure.universal.adapter import UniversalAdapter
    from conclave.infrastructure.universal.presets import get_preset

    # Preset laden (falls vorhanden)
    preset = get_preset(agent.preset) if agent.preset else {}

    # Agent-Felder haben Vorrang vor Preset
    api_url = agent.api_url or preset.get("api_url", "")
    response_path = agent.response_path or preset.get("response_path", "")
    message_format = agent.message_format if agent.message_format not in ("standard", "") else preset.get("message_format", "standard")
    auth_format = preset.get("auth_format", "bearer")
    usage_path = preset.get("usage_path", "usage")
    usage_input_key = preset.get("usage_input_key", "prompt_tokens")
    usage_output_key = preset.get("usage_output_key", "completion_tokens")
    extra_body = preset.get("extra_body", {})
    extracts_reasoning = preset.get("extracts_reasoning", False)

    if not api_url:
        return None

    return UniversalAdapter(
        api_url=api_url,
        api_key=api_key or agent.api_key,
        model=agent.model,
        response_path=response_path,
        message_format=message_format,
        system_prompt=agent.system_prompt or None,
        provider_name=agent.provider,
        auth_format=auth_format,
        usage_path=usage_path,
        usage_input_key=usage_input_key,
        usage_output_key=usage_output_key,
        extra_body=extra_body,
        extracts_reasoning=extracts_reasoning,
    )
