# src/conclave/api/server.py

import os
import sys

from conclave.api.app import create_app
from conclave.cli.bootstrap import (
    build_agent_service, validate_production_config,
)
from conclave.cli.config import ConclaveConfig
from conclave.cli.handler import CLIHandler
from conclave.infrastructure.auth import StaticKeyAuthService

def _seed_agents(agent_service):
    """Registriert Standard-Agents aus Env-Vars beim Start (idempotent).

    Env-Var Format: CONCLAVE_AGENT_<ID>=<provider>:<model>:<preset>:<name>
    Name ist optional, Default = ID.
    Beispiel: CONCLAVE_AGENT_GPT=openai-responses:gpt-5.6:openai-responses:GPT
              CONCLAVE_AGENT_Claude=anthropic:claude-sonnet-5:anthropic:Claude
              CONCLAVE_AGENT_Gemini=gemini:gemini-3.6-flash:gemini:Gemini
    """
    from conclave.domain.agent import Agent
    prefix = "CONCLAVE_AGENT_"
    # Suffixe die KEINE Agent-IDs sind, sondern Per-Agent-Konfiguration:
    # CONCLAVE_AGENT_<ID>_API_URL und _API_KEY werden vom Seed selbst gelesen,
    # duerfen aber nicht als eigene Agents geseeded werden.
    config_suffixes = ("_API_URL", "_API_KEY")
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        if any(key.endswith(s) for s in config_suffixes):
            continue
        agent_id = key[len(prefix):]
        parts = value.split(":", 3)
        if len(parts) < 2:
            continue
        provider = parts[0]
        model = parts[1]
        preset = parts[2] if len(parts) > 2 else ""
        name = parts[3] if len(parts) > 3 else agent_id
        api_url = os.environ.get(f"{prefix}{agent_id}_API_URL", "")
        api_key = os.environ.get(f"{prefix}{agent_id}_API_KEY", "")
        # Fallback: api_key_env aus dem Preset (z.B. DASHSCOPE_API_KEY,
        # DEEPSEEK_API_KEY) wenn kein per-Agent _API_KEY gesetzt ist.
        if not api_key and preset:
            try:
                from conclave.infrastructure.universal.presets import get_preset
                preset_data = get_preset(preset) or {}
                key_env = preset_data.get("api_key_env", "")
                if key_env:
                    api_key = os.environ.get(key_env, "")
            except Exception:
                pass
        try:
            try:
                existing = agent_service.get_agent(agent_id)
                if existing:
                    continue  # Agent existiert bereits
            except Exception:
                pass  # AgentNotFound — Agent muss erstellt werden
            agent = Agent(
                id=agent_id,
                name=name,
                provider=provider,
                model=model,
                preset=preset,
                api_url=api_url,
                api_key=api_key,
            )
            agent_service.upsert_agent(agent)
            print(f"Agent geseeded: {agent_id} ({provider}/{model})")
        except Exception as e:
            print(f"Agent-Seed fehlgeschlagen fuer {agent_id}: {e}")


def _build_postgres(config):
    """Baut alle Services mit PostgreSQL."""
    import psycopg2
    conn = psycopg2.connect(config.db_dsn)
    conn.autocommit = True

    from conclave.infrastructure.postgres.schema import initialize_schema
    initialize_schema(conn)

    from conclave.infrastructure.postgres.conversation_repository import PostgresConversationRepository
    from conclave.infrastructure.postgres.message_repository import PostgresMessageRepository
    from conclave.infrastructure.postgres.participant_repository import PostgresParticipantRepository
    from conclave.infrastructure.postgres.audit_repository import PostgresAuditRepository
    from conclave.infrastructure.postgres.agent_repository import PostgresAgentRepository
    from conclave.infrastructure.postgres.run_repository import PostgresRunRepository
    from conclave.application.conversation_flow import ConversationFlowService
    from conclave.application.agent_service import AgentService
    from pathlib import Path
    from conclave.infrastructure.crypto import CryptoService

    default_key_path = Path.home() / ".conclave" / "secret.key"
    crypto = CryptoService.load_or_generate(default_key_path)

    service = ConversationFlowService(
        conversation_repository=PostgresConversationRepository(conn),
        message_repository=PostgresMessageRepository(conn, crypto=crypto),
        participant_repository=PostgresParticipantRepository(conn),
    )
    service.set_audit_repository(PostgresAuditRepository(conn))
    service.set_run_repository(PostgresRunRepository(conn))

    agent_service = AgentService(PostgresAgentRepository(conn, crypto))

    return service, agent_service, conn


def _build_sqlite(config):
    """Baut alle Services mit SQLite."""
    import sqlite3
    conn = sqlite3.connect(str(config.db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")

    from conclave.infrastructure.sqlite.schema import initialize_schema
    initialize_schema(conn)

    from conclave.cli.bootstrap import build_service
    from conclave.infrastructure.sqlite.audit_repository import SQLiteAuditRepository
    from conclave.infrastructure.sqlite.run_repository import SQLiteRunRepository

    service = build_service(config=config, connection=conn)
    service.set_audit_repository(SQLiteAuditRepository(conn))
    service.set_run_repository(SQLiteRunRepository(conn))
    agent_service = build_agent_service(config=config, connection=conn)

    return service, agent_service, conn


def _build_app(config: ConclaveConfig | None = None):
    """Baut die Flask-App mit allen Services."""
    if config is None:
        config = ConclaveConfig.from_sources()

    errors = validate_production_config(config)
    if errors:
        raise RuntimeError(f"Production-Config ungueltig: {'; '.join(errors)}")

    # DB-Provider waehlen
    if config.db_provider == "postgres":
        service, agent_service, conn = _build_postgres(config)
    else:
        service, agent_service, conn = _build_sqlite(config)

    # Adapter-Registry
    from conclave.cli.bootstrap import build_registry
    build_registry(service, agent_service=agent_service, config=config)

    # Personal: keine Enterprise-Seeds und kein externes Policy-Gate.
    _seed_agents(agent_service)

    provider_fallback_keys = {
        "anthropic": config.anthropic_api_key,
        "openai": config.openai_api_key,
        "openai-responses": config.openai_api_key,
        "gemini": config.gemini_api_key,
    }
    handler = CLIHandler(service, agent_service=agent_service,
                         provider_fallback_keys=provider_fallback_keys)
    auth_service = StaticKeyAuthService(config.api_key) if config.api_key else None

    return create_app(handler, auth_service=auth_service,
                      agent_service=agent_service, config=config,
                      service=service), config


def create_wsgi_app():
    """WSGI-Factory fuer Gunicorn/uWSGI."""
    app, _ = _build_app()
    return app


def main() -> None:
    try:
        app, config = _build_app()
    except RuntimeError as e:
        print(f"FEHLER: {e}", file=sys.stderr)
        raise SystemExit(1)
    app.run(host=config.host, port=config.port, debug=config.debug)


if __name__ == "__main__":
    main()
