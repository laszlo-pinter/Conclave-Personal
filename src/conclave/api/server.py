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
from conclave.runtime.api_token import load_or_create_agent_token, load_or_create_token
from conclave.runtime.env import env_secret
from conclave.infrastructure.sqlite.connection import ThreadLocalConnection

def _seed_agents(agent_service):
    """Registriert Standard-Agents aus Env-Vars beim Start (idempotent).

    Env-Var Format: CONCLAVE_AGENT_<ID>=<provider>:<model>:<preset>:<name>
    Name ist optional, Default = ID.
    Beispiel: CONCLAVE_AGENT_GPT=openai-responses:<openai-model>:openai-responses:GPT
              CONCLAVE_AGENT_Claude=anthropic:<anthropic-model>:anthropic:Claude
              CONCLAVE_AGENT_Gemini=gemini:<gemini-model>:gemini:Gemini
    """
    from conclave.domain.agent import Agent
    prefix = "CONCLAVE_AGENT_"
    # Suffixe die KEINE Agent-IDs sind, sondern Per-Agent-Konfiguration:
    # CONCLAVE_AGENT_<ID>_API_URL und _API_KEY werden vom Seed selbst gelesen,
    # duerfen aber nicht als eigene Agents geseeded werden.
    config_suffixes = ("_API_URL", "_API_KEY")
    # Gleiches Praefix, aber keine Agents: das Agent-Token (Z1) und sein Dateipfad.
    reserved = {"CONCLAVE_AGENT_KEY", "CONCLAVE_AGENT_TOKEN_FILE"}
    for key, value in os.environ.items():
        if not key.startswith(prefix) or key in reserved:
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
        api_key = env_secret(f"{prefix}{agent_id}_API_KEY")
        # Fallback: api_key_env aus dem Preset (z.B. DASHSCOPE_API_KEY,
        # DEEPSEEK_API_KEY) wenn kein per-Agent _API_KEY gesetzt ist.
        if not api_key and preset:
            try:
                from conclave.infrastructure.universal.presets import get_preset
                preset_data = get_preset(preset) or {}
                key_env = preset_data.get("api_key_env", "")
                if key_env:
                    api_key = env_secret(key_env)
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
    from conclave.infrastructure.postgres.tool_event_repository import PostgresToolEventRepository
    from conclave.application.conversation_flow import ConversationFlowService
    from conclave.application.agent_service import AgentService
    from conclave.cli.bootstrap import _load_crypto

    # Wie SQLite: CONCLAVE_SECRET_KEY, CONCLAVE_SECRET_KEY_FILE, dann Plattform-Default (B8)
    crypto = _load_crypto()

    service = ConversationFlowService(
        conversation_repository=PostgresConversationRepository(conn),
        message_repository=PostgresMessageRepository(conn, crypto=crypto),
        participant_repository=PostgresParticipantRepository(conn),
    )
    service.set_audit_repository(PostgresAuditRepository(conn))
    service.set_run_repository(PostgresRunRepository(conn))
    service.set_tool_event_repository(PostgresToolEventRepository(conn))
    from conclave.infrastructure.postgres.context_report_repository import PostgresContextReportRepository
    service.set_context_report_repository(PostgresContextReportRepository(conn))

    agent_service = AgentService(PostgresAgentRepository(conn, crypto))

    return service, agent_service, conn


def _build_sqlite(config):
    """Baut alle Services mit SQLite."""
    # Eine Verbindung je Thread statt einer geteilten Verbindung (B6)
    conn = ThreadLocalConnection(config.db_path)

    from conclave.infrastructure.sqlite.schema import initialize_schema
    initialize_schema(conn)

    from conclave.cli.bootstrap import build_service
    from conclave.infrastructure.sqlite.audit_repository import SQLiteAuditRepository
    from conclave.infrastructure.sqlite.run_repository import SQLiteRunRepository
    from conclave.infrastructure.sqlite.tool_event_repository import SQLiteToolEventRepository

    service = build_service(config=config, connection=conn)
    service.set_audit_repository(SQLiteAuditRepository(conn, autocommit=True))
    service.set_run_repository(SQLiteRunRepository(conn))
    service.set_tool_event_repository(SQLiteToolEventRepository(conn, autocommit=True))
    from conclave.infrastructure.sqlite.context_report_repository import SQLiteContextReportRepository
    service.set_context_report_repository(SQLiteContextReportRepository(conn, autocommit=True))
    agent_service = build_agent_service(config=config, connection=conn)

    return service, agent_service, conn


def _build_consultations(service, agent_service, conn, config):
    """Consultations (Kanzo): Repository, Kanzo-Adapter, Ablauf, Worker, Anfragen."""
    from conclave.application.consultation_service import ConsultationService
    from conclave.application.consultation_worker import ConsultationWorker
    from conclave.application.consultations import ConsultationRequests
    from conclave.infrastructure.kanzo.adapter import KanzoMcpAdapter

    if config.db_provider == "postgres":
        from conclave.infrastructure.postgres.consultation_repository import PostgresConsultationRepository
        repo = PostgresConsultationRepository(conn)
    else:
        from conclave.infrastructure.sqlite.consultation_repository import SQLiteConsultationRepository
        repo = SQLiteConsultationRepository(conn, autocommit=True)

    def reviewer_name(agent_id: str) -> str:
        try:
            return agent_service.get_agent(agent_id).name
        except Exception:  # noqa: BLE001 - Anzeige-Name, Fallback auf die ID
            return agent_id

    kanzo = KanzoMcpAdapter(config.kanzo.url)
    processor = ConsultationService(service, repo, kanzo, kanzo,
                                    comment_max_chars=config.kanzo.comment_max_chars,
                                    reviewer_name=reviewer_name)
    worker = ConsultationWorker(repo, processor)
    requests = ConsultationRequests(repo, worker, kanzo, allowed_reviewers=config.kanzo.reviewers,
                                    max_per_hour=config.kanzo.max_per_hour,
                                    provider_label=processor.provider_label)
    return requests, worker


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
    # Token ist immer Pflicht (B2): ohne CONCLAVE_API_KEY wird die Token-Datei verwendet.
    if not config.api_key:
        config.api_key = load_or_create_token()
    # Agent-Token (Z1): ohne CONCLAVE_AGENT_KEY die Datei agent.token, angelegt wie api.token.
    if not config.agent_api_key:
        config.agent_api_key = load_or_create_agent_token()
    auth_service = StaticKeyAuthService(config.api_key, config.agent_api_key)

    consultations, worker = _build_consultations(service, agent_service, conn, config)
    app = create_app(handler, auth_service=auth_service,
                     agent_service=agent_service, config=config,
                     service=service, consultations=consultations)
    # Gestartet wird der Worker erst in runtime.serve.serve() (nicht hier, nicht in create_app)
    app.extensions["conclave_workers"] = [worker]
    if isinstance(conn, ThreadLocalConnection):
        _finish_transactions_per_request(app, conn)
    return app, config


def _finish_transactions_per_request(app, conn) -> None:
    """Keine offene Transaktion ueber das Ende einer Anfrage hinaus (B6).

    Mit einer Verbindung je Thread wuerde ein vergessener Commit den Schreib-Lock
    des Threads festhalten und alle anderen Schreiber blockieren.
    """
    @app.teardown_request
    def _finish(exc):
        if not conn.in_transaction:
            return
        if exc is None:
            conn.commit()
        else:
            conn.rollback()


def create_wsgi_app():
    """WSGI-Factory fuer Gunicorn/uWSGI."""
    app, _ = _build_app()
    return app


def main() -> None:
    from conclave.infrastructure.log import LOG_FILE_NAME, configure_logging
    from conclave.runtime.paths import get_runtime_paths

    config = ConclaveConfig.from_sources()
    configure_logging(config.log_level, get_runtime_paths().log_dir / LOG_FILE_NAME)
    try:
        app, config = _build_app(config)
    except RuntimeError as e:
        print(f"FEHLER: {e}", file=sys.stderr)
        raise SystemExit(1)
    from conclave.runtime.serve import serve
    serve(app, config.host, config.port, debug=config.debug)


if __name__ == "__main__":
    main()
