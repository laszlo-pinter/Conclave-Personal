# src/conclave/api/app.py

import json as _json
import logging
import os
import time

try:
    from flask import Flask, Response, g, jsonify, request, stream_with_context, send_file as flask_send_file
    from werkzeug.exceptions import HTTPException
except ImportError:
    raise ImportError(
        "Das 'flask'-Paket ist nicht installiert. "
        "Bitte installieren mit: pip install conclave[api]"
    )

from conclave.cli.handler import (
    CLIHandler,
    CLIResult,
    normalize_auto_loop_options,
    normalize_parallel_groups,
    normalize_participant_sequence,
)
from conclave.domain.errors import (
    AdapterNotFound,
    AgentAlreadyExists,
    AgentNotFound,
    AuthenticationError,
    ConversationNotFound,
    EmptyConversation,
    FloorNotGranted,
    NoFloorGranted,
    ParticipantAlreadyRegistered,
    ParticipantNotRegistered,
    ProviderError,
    ProviderRateLimit,
    ProviderTimeout,
)
from conclave.domain.participant import ParticipantType
from conclave.domain.principal import HUMAN_PRINCIPAL
from conclave.api.access import HUMAN_ONLY_ERROR, agent_may
from conclave.application.consultations import ConsultationRequestError
from conclave.application.board import BoardError, comment_to_dict, event_to_dict, project_to_dict, task_to_dict
from conclave.domain.errors import TaskNotFound, TaskSourceError
from conclave.cli.bootstrap import rate_limit_disabled, validate_rate_limit
from conclave.cli.config import DEFAULT_RATE_LIMIT
from conclave.application.workspace_security import (
    agent_read_limit_bytes,
    assert_size_allowed,
    is_hidden_workspace_path,
    resolve_workspace_path,
    workspace_root,
    text_size,
    ui_read_limit_bytes,
    write_limit_bytes,
)
from conclave.infrastructure.log import active_log_file, get_logger, read_log_tail
from conclave.runtime.toml_edit import set_toml_string
from conclave.runtime.backup import create_backup_archive, restore_backup_archive
from conclave.runtime.assets import get_asset_root
from conclave.runtime.env import env_secret

try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    _has_limiter = True
except ImportError:
    _has_limiter = False

logger = get_logger("api")

# Alle Ressourcen kommen vom eigenen Server (B5). Inline-Skripte und <style>-Bloecke
# sind verboten; nur style-Attribute sind erlaubt (die UI setzt Farben per Attribut).
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "style-src-attr 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "frame-ancestors 'none'",
    "form-action 'self'",
])
# Mikrofon nur fuer die eigene Seite (Spracheingabe in speech.js)
PERMISSIONS_POLICY = "camera=(), geolocation=(), microphone=(self), payment=(), usb=()"

# Ohne Token erreichbar (B12): UI-Seite, statische Dateien, Healthcheck, API-Doku.
PUBLIC_GET_PATHS = frozenset({"/", "/health", "/api-docs", "/openapi.json"})
CLIENT_HEADER = "X-Conclave-Client"

# Host-Allowlist gegen DNS-Rebinding (B2). Loopback-Namen sind immer erlaubt,
# CONCLAVE_ALLOWED_HOSTS ergaenzt sie. Eintraege ohne Port gelten fuer jeden Port.
DEFAULT_ALLOWED_HOSTS = "localhost,127.0.0.1,[::1]"


def _split_host(value: str) -> tuple[str, str]:
    """'Host'-Wert in (hostname, port) zerlegen; IPv6 in eckigen Klammern oder nackt."""
    value = value.strip().lower()
    if value.startswith("["):
        host, _, rest = value[1:].partition("]")
        if rest and not rest.startswith(":"):
            return value, ""  # fehlerhaft, z. B. "[::1].evil" - passt auf keinen Eintrag
        return host, rest[1:]
    if value.count(":") == 1:
        host, port = value.split(":")
        return host, port
    return value, ""


def parse_allowed_hosts(raw: str) -> set[tuple[str, str]]:
    entries = f"{DEFAULT_ALLOWED_HOSTS},{raw or ''}".split(",")
    return {_split_host(entry) for entry in entries if entry.strip()}


def is_host_allowed(host_header: str, allowed: set[tuple[str, str]]) -> bool:
    host, port = _split_host(host_header or "")
    return bool(host) and ((host, "") in allowed or (host, port) in allowed)


def create_app(handler: CLIHandler, auth_service=None,
               agent_service=None, config=None, service=None, consultations=None, board=None) -> Flask:
    import pathlib
    asset_root = get_asset_root()
    app = Flask(__name__, static_folder=str(asset_root / "static"), static_url_path="/static")
    WORKSPACE = str(workspace_root())

    def _refresh_registry():
        """Invalidiert den Adapter-Cache — Lazy Builder baut bei Bedarf neu."""
        if service and hasattr(service, '_registry') and service._registry:
            service._registry.invalidate()

    # Rate-Limit pro Anfrage gelesen: Aenderungen ueber PUT /settings wirken sofort.
    rate_limit_state = {
        "value": getattr(config, "rate_limit", DEFAULT_RATE_LIMIT) if config else DEFAULT_RATE_LIMIT,
        "source": getattr(config, "rate_limit_source", "default") if config else "default",
    }

    def _current_rate_limit() -> str:
        value = rate_limit_state["value"]
        return DEFAULT_RATE_LIMIT if rate_limit_disabled(value) else value

    if _has_limiter:
        limiter = Limiter(get_remote_address, app=app, default_limits=[_current_rate_limit],
                          default_limits_exempt_when=lambda: rate_limit_disabled(rate_limit_state["value"]),
                          storage_uri="memory://")

    @app.errorhandler(429)
    def _rate_limited(e):
        return jsonify({"error": f"Zu viele Anfragen ({e.description}).", "type": "RateLimitExceeded"}), 429

    _allowed_hosts = parse_allowed_hosts(
        getattr(config, "allowed_hosts", "") or os.environ.get("CONCLAVE_ALLOWED_HOSTS", "")
    )

    @app.before_request
    def _check_host():
        if not is_host_allowed(request.host, _allowed_hosts):
            return jsonify({"error": "Host nicht erlaubt.", "type": "InvalidHost"}), 421

    @app.before_request
    def _check_csrf():
        # Ohne CORS-Preflight senden Browser Cross-Site nur GET/HEAD/POST mit
        # "einfachem" Content-Type. PUT/DELETE loesen immer einen Preflight aus.
        # Fuer POST erzwingen JSON oder ein eigener Header den Preflight (B3).
        if request.method != "POST" or request.routing_exception is not None:
            return  # unbekannte Routen liefern weiter 404/405
        if request.mimetype == "application/json" or CLIENT_HEADER in request.headers:
            return
        return jsonify({
            "error": f"Content-Type application/json oder Header {CLIENT_HEADER} erforderlich.",
            "type": "UnsupportedMediaType",
        }), 415

    @app.before_request
    def _authenticate():
        if request.method == "OPTIONS":
            return
        if auth_service is None:
            g.principal = HUMAN_PRINCIPAL      # ohne Auth (nur Tests/Entwicklung): voller Zugang
            return
        if request.method in ("GET", "HEAD") and (
            request.path in PUBLIC_GET_PATHS or request.path.startswith("/static/")
        ):
            return
        token = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        else:
            token = request.headers.get("X-API-Key")
        principal = auth_service.authenticate(token)
        if principal is None:
            raise AuthenticationError()
        g.principal = principal

    @app.before_request
    def _check_agent_access():
        # Z2: Agenten duerfen nur, was auf der Allowlist steht (Default deny).
        principal = g.get("principal")
        if principal is None or not principal.is_agent or request.method == "OPTIONS":
            return
        if request.url_rule is None:
            return  # unbekannte Route: 404/405 wie bei allen anderen
        if not agent_may(request.method, request.url_rule.rule):
            return jsonify(HUMAN_ONLY_ERROR), 403

    @app.before_request
    def _log_request_start():
        request._start_time = time.monotonic()
        logger.debug("request start: %s %s", request.method, request.path)

    @app.after_request
    def _log_request_end(response):
        duration_ms = (time.monotonic() - getattr(request, "_start_time", time.monotonic())) * 1000
        # Erfolgreiche Lesezugriffe (statische Dateien, UI-Polling) nur auf DEBUG,
        # damit Warnungen und Fehler im Server-Log nicht untergehen.
        quiet = request.method in ("GET", "HEAD", "OPTIONS") and response.status_code < 400
        logger.log(
            logging.DEBUG if quiet else logging.INFO,
            "%s %s → %d (%.1f ms)",
            request.method, request.path, response.status_code, duration_ms,
            extra={"method": request.method, "path": request.path,
                   "status": response.status_code, "duration_ms": duration_ms},
        )
        return response

    # CORS-Allowlist aus Env-Var (Default: localhost/127.0.0.1-Varianten fuer lokale Entwicklung).
    # file://-Origins ("null") sind nicht standardmaessig erlaubt. Wer eine
    # lokale Datei-UI bewusst nutzt, muss "null" explizit konfigurieren.
    _cors_allowed = {
        o.strip()
        for o in os.environ.get(
            "CONCLAVE_ALLOWED_ORIGINS",
            "http://localhost,http://localhost:8000,http://127.0.0.1,http://127.0.0.1:8000"
        ).split(",")
        if o.strip()
    }

    @app.after_request
    def _notify_on_new_content(response):
        """Schreibt Marker-Datei bei erfolgreichen POST-Requests (neue Messages/Invokes)."""
        if request.method == "POST" and response.status_code in (200, 201):
            path = request.path
            # Nur bei relevanten Endpoints notifizieren
            if "/messages" in path or "/invoke" in path or "/orchestrate" in path:
                conv_id = path.split("/conversations/")[1].split("/")[0] if "/conversations/" in path else ""
                _notify_new_message(conv_id, 0)
        return response

    @app.after_request
    def _security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = PERMISSIONS_POLICY
        # CORS: nur explizit konfigurierte Origins, kein Wildcard-Reflect
        origin = request.headers.get("Origin", "")
        if origin and origin in _cors_allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Headers"] = f"Content-Type, Authorization, X-API-Key, {CLIENT_HEADER}"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        return response

    @app.route("/", defaults={"path": ""}, methods=["OPTIONS"])
    @app.route("/<path:path>", methods=["OPTIONS"])
    def _cors_preflight(path):
        return "", 204

    # ── UI Serving ────────────────────────────────────────────────────────

    def _notify_new_message(conversation_id: str, sequence: int, author: str = ""):
        """Schreibt eine Marker-Datei bei neuer Nachricht (fuer FileChanged Hook)."""
        marker = workspace_root() / "conclave_notify.json"
        try:
            marker.write_text(_json.dumps({
                "event": "new_message",
                "conversation_id": conversation_id,
                "sequence": sequence,
                "author": author,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }))
        except Exception:
            pass

    @app.get("/")
    def serve_ui():
        ui_path = asset_root / "conclave-ui.html"
        if ui_path.is_file():
            return flask_send_file(str(ui_path), mimetype="text/html")
        return "UI nicht gefunden", 404

    @app.get("/api-docs")
    def swagger_ui():
        """Swagger UI — interaktive API-Dokumentation."""
        return """<!DOCTYPE html>
<html><head>
<title>Conclave API</title>
<meta charset="utf-8">
<link rel="stylesheet" href="/static/vendor/swagger-ui/swagger-ui.css">
</head><body>
<div id="swagger-ui"></div>
<script src="/static/vendor/swagger-ui/swagger-ui-bundle.js"></script>
<script src="/static/js/swagger-init.js"></script>
</body></html>""", 200, {"Content-Type": "text/html"}

    @app.get("/openapi.json")
    def openapi_spec():
        """OpenAPI 3.0 Spec als JSON."""
        spec_path = asset_root / "static" / "openapi.json"
        if spec_path.is_file():
            return flask_send_file(str(spec_path), mimetype="application/json")
        return jsonify({"error": "OpenAPI spec nicht gefunden. python scripts/gen-openapi.py ausfuehren."}), 404

    @app.get("/health")
    def health():
        """Healthcheck fuer lokale Runtime und Integrationen."""
        return jsonify({"status": "ok", "product": "conclave-personal"}), 200

    @app.get("/auth/whoami")
    def whoami():
        """Rolle des anfragenden Tokens: human oder agent."""
        return jsonify({"role": g.principal.role}), 200

    # ── Error Handler ────────────────────────────────────────────────────

    def _error_json(e: Exception, status: int):
        return jsonify({"error": str(e), "type": type(e).__name__}), status

    def _cli_error_json(result: CLIResult, default_status: int):
        data = result.data or {}
        status = int(data.get("status", default_status))
        payload = {"error": result.message}
        if data.get("type"):
            payload["type"] = data["type"]
        return jsonify(payload), status

    @app.errorhandler(AuthenticationError)
    def _handle_authentication_error(e):
        return _error_json(e, 401)

    @app.errorhandler(ConversationNotFound)
    def _handle_conversation_not_found(e):
        return _error_json(e, 404)

    @app.errorhandler(ParticipantNotRegistered)
    def _handle_participant_not_registered(e):
        return _error_json(e, 404)

    @app.errorhandler(AgentNotFound)
    def _handle_agent_not_found(e):
        return _error_json(e, 404)

    @app.errorhandler(ParticipantAlreadyRegistered)
    def _handle_participant_already_registered(e):
        return _error_json(e, 409)

    @app.errorhandler(AgentAlreadyExists)
    def _handle_agent_already_exists(e):
        return _error_json(e, 409)

    @app.errorhandler(NoFloorGranted)
    def _handle_no_floor_granted(e):
        return _error_json(e, 409)

    @app.errorhandler(EmptyConversation)
    def _handle_empty_conversation(e):
        return _error_json(e, 400)

    @app.errorhandler(FloorNotGranted)
    def _handle_floor_not_granted(e):
        return _error_json(e, 409)

    @app.errorhandler(AdapterNotFound)
    def _handle_adapter_not_found(e):
        return _error_json(e, 502)

    @app.errorhandler(ProviderRateLimit)
    def _handle_provider_rate_limit(e):
        return _error_json(e, 429)

    @app.errorhandler(ProviderTimeout)
    def _handle_provider_timeout(e):
        return _error_json(e, 504)

    @app.errorhandler(ProviderError)
    def _handle_provider_error(e):  # ProviderUnavailable und sonstige Provider-Fehler
        return _error_json(e, 502)

    @app.errorhandler(ValueError)
    def _handle_value_error(e):
        return _error_json(e, 400)

    @app.errorhandler(ConsultationRequestError)
    def _handle_consultation_request(e):
        return jsonify({"error": str(e), "type": e.type}), e.status

    @app.errorhandler(BoardError)
    def _handle_board_error(e):
        return jsonify({"error": str(e), "type": e.type}), e.status

    @app.errorhandler(TaskNotFound)
    def _handle_task_not_found(e):
        return _error_json(e, 404)

    @app.errorhandler(TaskSourceError)
    def _handle_task_source(e):  # Kanzo nicht erreichbar oder unbekanntes Format
        return _error_json(e, 502)

    @app.errorhandler(HTTPException)
    def _handle_http_exception(e):
        return jsonify({"error": e.description, "type": type(e).__name__}), e.code

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        logger.exception("Unhandled exception: %s", e)
        return jsonify({"error": "Internal server error", "type": "InternalError"}), 500

    # ── POST /conversations ──────────────────────────────────────────────

    @app.post("/conversations")
    def create_conversation():
        result = handler.new_conversation()
        return jsonify(result.data), 201

    # ── GET /conversations ───────────────────────────────────────────────

    @app.get("/conversations")
    def list_conversations():
        result = handler.list_conversations()
        return jsonify(result.data), 200

    # ── Agents ───────────────────────────────────────────────────────────

    @app.get("/agents")
    def list_agents():
        result = handler.list_agents()
        return jsonify(result.data), 200

    @app.get("/agents/<agent_id>")
    def get_agent(agent_id: str):
        result = handler.get_agent(agent_id)
        if not result.success:
            return jsonify({"error": result.message}), 404
        return jsonify(result.data), 200

    def _max_messages_from(body: dict, current=None):
        """max_messages aus dem Request: fehlt das Feld, bleibt ``current``; null = Default."""
        if "max_messages" not in body:
            return current
        value = body["max_messages"]
        if value is None or value == "":
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("max_messages muss leer oder eine ganze Zahl >= 0 sein.")
        return value

    @app.post("/agents")
    def create_agent():
        from conclave.domain.agent import Agent
        body = request.get_json() or {}
        agent_id = body.get("id")
        name     = body.get("name")
        provider = body.get("provider", "anthropic")
        model    = body.get("model", "")
        if not agent_id or not name or not model:
            return jsonify({"error": "id, name und model sind erforderlich."}), 400
        try:
            agent = Agent(
                id=agent_id, name=name, provider=provider, model=model,
                api_key=body.get("api_key", ""),
                role=body.get("role", ""), topic=body.get("topic", ""),
                system_prompt=body.get("system_prompt", ""),
                preset=body.get("preset", ""),
                api_url=body.get("api_url", ""),
                response_path=body.get("response_path", ""),
                message_format=body.get("message_format", "standard"),
                max_messages=_max_messages_from(body),
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        result = handler.create_agent(agent)
        if not result.success:
            return jsonify({"error": result.message}), 409
        _refresh_registry()
        return jsonify(result.data), 201

    @app.put("/agents/<agent_id>")
    def update_agent(agent_id: str):
        from conclave.domain.agent import Agent
        body = request.get_json() or {}
        name     = body.get("name")
        provider = body.get("provider", "anthropic")
        model    = body.get("model", "")
        if not name or not model:
            return jsonify({"error": "name und model sind erforderlich."}), 400
        try:
            existing = handler.get_agent(agent_id)
            created_at = None
            # Ohne Angabe bleibt das gespeicherte Limit erhalten (wie beim API-Key)
            max_messages = _max_messages_from(
                body, existing.data.get("max_messages") if existing.success else None)
            if existing.success:
                from datetime import datetime
                created_at = datetime.fromisoformat(existing.data["created_at"])
            agent = Agent(
                id=agent_id, name=name, provider=provider, model=model,
                api_key=body.get("api_key", ""),
                role=body.get("role", ""), topic=body.get("topic", ""),
                system_prompt=body.get("system_prompt", ""),
                preset=body.get("preset", ""),
                api_url=body.get("api_url", ""),
                response_path=body.get("response_path", ""),
                message_format=body.get("message_format", "standard"),
                max_messages=max_messages,
                created_at=created_at,
            )
        except (ValueError, Exception) as e:
            return jsonify({"error": str(e)}), 400
        # Ohne neuen api_key bleibt der gespeicherte Key erhalten; entfernen nur ausdruecklich
        result = handler.update_agent(agent, clear_api_key=body.get("clear_api_key") is True)
        if not result.success:
            return jsonify({"error": result.message}), 404
        _refresh_registry()
        return jsonify(result.data), 200

    @app.delete("/agents/<agent_id>")
    def delete_agent(agent_id: str):
        result = handler.delete_agent(agent_id)
        if not result.success:
            return jsonify({"error": result.message}), 404
        _refresh_registry()
        return "", 204

    @app.get("/presets")
    def list_presets():
        from conclave.infrastructure.universal.presets import list_presets as _list
        return jsonify({"presets": _list()}), 200

    @app.get("/agent-roles")
    def list_agent_roles():
        from conclave.domain.agent_roles import list_agent_roles as _list
        return jsonify({"roles": _list()}), 200

    @app.get("/providers")
    def list_providers():
        """Listet verfuegbare Provider-Presets ohne Secrets."""
        from conclave.infrastructure.universal.presets import list_presets as _list

        fallback_keys = {
            "anthropic": getattr(config, "anthropic_api_key", "") if config else "",
            "openai": getattr(config, "openai_api_key", "") if config else "",
            "openai-responses": getattr(config, "openai_api_key", "") if config else "",
            "gemini": getattr(config, "gemini_api_key", "") if config else "",
        }
        providers = []
        for preset in _list():
            name = preset.get("name", "")
            key_env = preset.get("api_key_env", "")
            requires_api_key = bool(preset.get("requires_api_key", True))
            key_available = (
                not requires_api_key
                or bool(fallback_keys.get(name))
                or bool(key_env and env_secret(key_env))
            )
            providers.append({
                "name": name,
                "label": preset.get("label", name),
                "description": preset.get("description", ""),
                "models": preset.get("models", []),
                "recommended": bool(preset.get("recommended", False)),
                "local": not requires_api_key,
                "requires_api_key": requires_api_key,
                "api_key_env": key_env,
                "api_key_available": key_available,
                "api_key_configured": key_available,
            })
        return jsonify({"providers": providers}), 200

    @app.post("/agents/<agent_id>/test")
    def test_agent(agent_id: str):
        result = handler.test_agent(agent_id)
        return jsonify(result), 200

    # ── DELETE /conversations/<id> ───────────────────────────────────────

    @app.delete("/conversations/<conversation_id>")
    def delete_conversation(conversation_id: str):
        result = handler.delete_conversation(conversation_id)
        if not result.success:
            return jsonify({"error": result.message}), 404
        return "", 204

    # ── POST /conversations/<id>/topic ───────────────────────────────────

    @app.post("/conversations/<conversation_id>/topic")
    def set_topic(conversation_id: str):
        body = request.get_json() or {}
        topic = body.get("topic")
        if topic is None:
            return jsonify({"error": "topic ist erforderlich."}), 400
        result = handler.set_topic(conversation_id, topic)
        if not result.success:
            return jsonify({"error": result.message}), 404
        return jsonify(result.data), 200

    # ── Chat-Regeln ───────────────────────────────────────────────────────

    @app.get("/conversations/<conversation_id>/rules")
    def get_rules(conversation_id: str):
        result = handler.show_conversation(conversation_id)
        if not result.success:
            return jsonify({"error": result.message}), 404
        return jsonify({"rules": result.data.get("rules", "")}), 200

    @app.post("/conversations/<conversation_id>/rules")
    def set_rules(conversation_id: str):
        body = request.get_json() or {}
        rules = body.get("rules", "")
        result = handler.set_rules(conversation_id, rules)
        if not result.success:
            return jsonify({"error": result.message}), 404
        return jsonify({"rules": rules}), 200

    # ── Floor management ─────────────────────────────────────────────────

    @app.post("/conversations/<conversation_id>/floor/grant")
    def grant_floor(conversation_id: str):
        body = request.get_json() or {}
        participant_id = body.get("participant_id")
        if not participant_id:
            return jsonify({"error": "participant_id ist erforderlich."}), 400
        result = handler.grant_floor(conversation_id, participant_id)
        if not result.success:
            return jsonify({"error": result.message}), 404
        return jsonify(result.data), 200

    @app.post("/conversations/<conversation_id>/floor/revoke")
    def revoke_floor(conversation_id: str):
        result = handler.revoke_floor(conversation_id)
        if not result.success:
            return jsonify({"error": result.message}), 404
        return jsonify(result.data), 200

    @app.post("/conversations/<conversation_id>/floor/invoke")
    def invoke_with_floor(conversation_id: str):
        result = handler.invoke_with_floor(conversation_id)
        if not result.success:
            return _cli_error_json(result, 409)
        return jsonify(result.data), 200

    # ── GET /conversations/<id> ──────────────────────────────────────────

    @app.get("/conversations/<conversation_id>")
    def get_conversation(conversation_id: str):
        result = handler.show_conversation(conversation_id)
        if not result.success:
            return jsonify({"error": result.message}), 404
        return jsonify(result.data), 200

    @app.get("/conversations/<conversation_id>/messages/<message_id>/context")
    def get_message_context(conversation_id: str, message_id: str):
        result = handler.message_context(conversation_id, message_id)
        if not result.success:
            return _cli_error_json(result, 404)
        return jsonify(result.data), 200

    @app.get("/conversations/<conversation_id>/participants/<participant_id>/context-preview")
    def get_context_preview(conversation_id: str, participant_id: str):
        result = handler.context_preview(conversation_id, participant_id)
        if not result.success:
            return _cli_error_json(result, 404)
        return jsonify(result.data), 200

    @app.get("/conversations/<conversation_id>/tool-events")
    def list_tool_events(conversation_id: str):
        result = handler.list_tool_events(conversation_id)
        if not result.success:
            return jsonify({"error": result.message}), 404
        return jsonify(result.data), 200

    # ── POST /conversations/<id>/participants ────────────────────────────

    @app.post("/conversations/<conversation_id>/participants")
    def add_participant(conversation_id: str):
        body = request.get_json() or {}
        participant_id = body.get("participant_id") or body.get("id")
        name = body.get("name")
        ptype_str = body.get("type", "model")

        if not participant_id or not name:
            return jsonify({"error": "participant_id und name sind erforderlich.", "type": "ValidationError"}), 400
        if ptype_str not in ("model", "user"):
            return jsonify({"error": "type muss 'model' oder 'user' sein.", "type": "ValidationError"}), 400
        # Z2b: Agenten treten nie als Mensch auf, also keine Participants vom Typ user.
        if g.principal.is_agent and ptype_str != "model":
            return jsonify(HUMAN_ONLY_ERROR), 403

        ptype = ParticipantType.MODEL if ptype_str == "model" else ParticipantType.USER
        result = handler.add_participant(
            conversation_id=conversation_id,
            participant_id=participant_id,
            name=name,
            participant_type=ptype,
        )
        if not result.success:
            return jsonify({"error": result.message}), 409
        return jsonify(result.data), 201

    @app.delete("/conversations/<conversation_id>/participants/<participant_id>")
    def delete_participant(conversation_id: str, participant_id: str):
        result = handler.delete_participant(conversation_id, participant_id)
        if not result.success:
            return jsonify({"error": result.message}), 404
        return "", 204

    # ── POST /conversations/<id>/messages ────────────────────────────────

    @app.post("/conversations/<conversation_id>/messages")
    def add_message(conversation_id: str):
        body = request.get_json() or {}
        content = body.get("content")

        if not content:
            return jsonify({"error": "content ist erforderlich."}), 400

        result = handler.add_message(conversation_id, content, origin=g.principal.role)  # Z4
        if not result.success:
            return jsonify({"error": result.message}), 404
        return jsonify(result.data), 201

    # ── POST /conversations/<id>/participants/<pid>/invoke ───────────────

    @app.post("/conversations/<conversation_id>/participants/<participant_id>/invoke")
    def invoke_participant(conversation_id: str, participant_id: str):
        result = handler.invoke_participant(conversation_id, participant_id)
        if not result.success:
            return _cli_error_json(result, 502)
        return jsonify(result.data), 200

    # ── POST /conversations/<id>/orchestrate ─────────────────────────────

    @app.post("/conversations/<conversation_id>/orchestrate")
    def orchestrate(conversation_id: str):
        body = request.get_json() or {}
        try:
            sequence = normalize_participant_sequence(body.get("sequence"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        result = handler.orchestrate(conversation_id, sequence)
        if not result.success:
            return _cli_error_json(result, 502)
        return jsonify(result.data), 200

    # ── POST /conversations/<id>/orchestrate-parallel ─────────────────────

    @app.post("/conversations/<conversation_id>/orchestrate-parallel")
    def orchestrate_parallel(conversation_id: str):
        body = request.get_json() or {}
        try:
            groups = normalize_parallel_groups(body.get("groups"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        result = handler.orchestrate_parallel(conversation_id, groups)
        if not result.success:
            return _cli_error_json(result, 502)
        return jsonify(result.data), 200

    @app.post("/conversations/<conversation_id>/orchestrate-parallel-stream")
    def orchestrate_parallel_stream(conversation_id: str):
        body = request.get_json() or {}
        try:
            groups = normalize_parallel_groups(body.get("groups"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        def generate():
            try:
                for event in handler.orchestrate_parallel_stream(conversation_id, groups):
                    yield f"data: {_json.dumps(event)}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                logger.exception("orchestrate-parallel-stream Fehler: %s", e)
                yield f"data: {_json.dumps({'event': 'stop', 'reason': 'error', 'message': str(e)})}\n\n"
                yield "data: [DONE]\n\n"

        return Response(
            stream_with_context(generate()),
            content_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── GET /conversations/<id>/participants/<pid>/stream ────────────────

    @app.get("/conversations/<conversation_id>/participants/<participant_id>/stream")
    def stream_participant(conversation_id: str, participant_id: str):
        def generate():
            try:
                for token in handler.stream_participant(conversation_id, participant_id):
                    yield f"data: {token}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                yield f"data: [ERROR] {e}\n\n"

        return Response(
            stream_with_context(generate()),
            content_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # ── POST /conversations/<id>/auto-loop ─────────────────────────────────
    # Automatischer Gespraechsaustausch zwischen Participants als SSE-Stream.

    @app.post("/conversations/<conversation_id>/auto-loop")
    def auto_loop(conversation_id: str):
        body = request.get_json() or {}
        try:
            sequence, stop_signal, max_rounds, rotation = normalize_auto_loop_options(
                sequence=body.get("sequence"),
                stop_signal=body.get("stop_signal", "@done"),
                max_rounds=body.get("max_rounds", 20),
                rotation=body.get("rotation", "none"),
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        def generate():
            try:
                for event in handler.auto_loop(
                    conversation_id=conversation_id,
                    sequence=sequence,
                    stop_signal=stop_signal,
                    max_rounds=max_rounds,
                    rotation=rotation,
                ):
                    yield f"data: {_json.dumps(event)}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                logger.exception("auto-loop Fehler: %s", e)
                yield f"data: {_json.dumps({'event': 'stop', 'reason': 'error', 'message': str(e)})}\n\n"
                yield "data: [DONE]\n\n"

        return Response(
            stream_with_context(generate()),
            content_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── Consultations (Zweitmeinung zu Kanzo-Tickets) ────────────────────

    def _consultations():
        if consultations is None:
            raise ConsultationRequestError("Consultations sind in dieser Instanz nicht verfuegbar.",
                                           503, "ConsultationsDisabled")
        return consultations

    @app.post("/consultations")
    def create_consultation():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "JSON-Objekt erwartet.", "type": "ValidationError"}), 400
        return jsonify(_consultations().create(body, g.principal)), 202

    @app.get("/consultations")
    def list_consultations():
        return jsonify(_consultations().list_for(request.args.get("source_ref", ""))), 200

    @app.get("/consultations/<consultation_id>")
    def get_consultation(consultation_id: str):
        return jsonify(_consultations().get(consultation_id)), 200

    @app.post("/consultations/<consultation_id>/retry")
    def retry_consultation(consultation_id: str):
        body = request.get_json(silent=True) or {}
        rerun = body.get("rerun", False)
        if not isinstance(rerun, bool):
            return jsonify({"error": "rerun muss true oder false sein.", "type": "ValidationError"}), 400
        result = _consultations().retry(consultation_id, g.principal, rerun=rerun)
        return jsonify(result), 202

    # ── Board (Plan board.md, B3) ───────────────────────────────────────
    def _board():
        if board is None:
            raise BoardError("Das Board ist in dieser Instanz nicht verfuegbar.", 503, "BoardDisabled")
        return board

    def _json_object() -> dict:
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise BoardError("JSON-Objekt erwartet.", 400, "ValidationError")
        return body

    def _flag(name: str, default: bool = False) -> bool:
        return request.args.get(name, "true" if default else "false").lower() in ("1", "true", "yes")

    @app.get("/board")
    def board_overview():
        """Spalten, Projekte und Aenderungszaehler des Boards."""
        b = _board()
        return jsonify({"statuses": list(b.flow.statuses), "projects": [project_to_dict(p) for p in b.list_projects()],
                        "changes": b.change_token()}), 200

    @app.get("/board/changes")
    def board_changes():
        """Aenderungszaehler; die UI laedt neu, wenn er steigt."""
        return jsonify({"changes": _board().change_token()}), 200

    @app.post("/board/projects")
    def board_create_project():
        """Projekt anlegen (Freigabe-Recht)."""
        body = _json_object()
        project = _board().create_project(g.principal, body.get("slug"), body.get("name"))
        return jsonify(project_to_dict(project)), 201

    @app.put("/board/projects/<slug>")
    def board_rename_project(slug: str):
        """Projekt umbenennen (Freigabe-Recht)."""
        project = _board().rename_project(g.principal, slug, _json_object().get("name"))
        return jsonify(project_to_dict(project)), 200

    @app.delete("/board/projects/<slug>")
    def board_delete_project(slug: str):
        """Projekt samt Tickets loeschen (Freigabe-Recht)."""
        _board().delete_project(g.principal, slug)
        return "", 204

    @app.get("/board/tasks")
    def board_list_tasks():
        """Tickets in Board-Reihenfolge; Filter project, status (mehrfach), include_done."""
        statuses = request.args.getlist("status") or None
        tasks = _board().list_tasks(request.args.get("project") or None, statuses,
                                    include_done=_flag("include_done"))
        return jsonify({"tasks": [task_to_dict(t) for t in tasks]}), 200

    @app.post("/board/tasks")
    def board_create_task():
        """Ticket anlegen; neue Tickets landen in der ersten Spalte."""
        body = _json_object()
        tags = body.get("tags") or []
        if not isinstance(tags, list):
            raise BoardError("tags muss eine Liste sein.", 400, "ValidationError")
        task = _board().create_task(g.principal, body.get("project"), body.get("title"),
                                    description=body.get("description") or "", tags=tags,
                                    human=bool(body.get("human", False)), status=body.get("status"))
        return jsonify(task_to_dict(task)), 201

    @app.get("/board/search")
    def board_search():
        """Suche in Titel, Tags, Beschreibung und Kommentaren."""
        tasks = _board().search(request.args.get("q", ""), request.args.get("project") or None,
                                include_done=_flag("include_done", True))
        return jsonify({"tasks": [task_to_dict(t) for t in tasks]}), 200

    @app.post("/board/next")
    def board_next_task():
        """Oberstes freies Ticket der ersten Spalte uebernehmen (atomar)."""
        body = request.get_json(silent=True) or {}
        task = _board().next_task(g.principal, body.get("project") or None)
        return jsonify({"task": task_to_dict(task) if task else None}), 200

    def _ref(slug: str, number: int) -> str:
        return f"{slug}#{number}"

    @app.get("/board/projects/<slug>/tasks/<int:number>")
    def board_get_task(slug: str, number: int):
        """Ein Ticket mit Kommentaren."""
        b = _board()
        task = b.get_task(_ref(slug, number))
        return jsonify({**task_to_dict(task), "comments": [comment_to_dict(c) for c in b.comments(task.ref)]}), 200

    @app.patch("/board/projects/<slug>/tasks/<int:number>")
    def board_update_task(slug: str, number: int):
        """Ticket aendern: title, description, tags, status, human, index (Position in der Spalte)."""
        body = _json_object()
        unknown = set(body) - {"title", "description", "tags", "status", "human", "index"}
        if unknown:
            raise BoardError(f"Unbekannte Felder: {sorted(unknown)}", 400, "ValidationError")
        tags = body.get("tags")
        if tags is not None and not isinstance(tags, list):
            raise BoardError("tags muss eine Liste sein.", 400, "ValidationError")
        index = body.get("index")
        if index is not None and (isinstance(index, bool) or not isinstance(index, int)):
            raise BoardError("index muss eine ganze Zahl sein.", 400, "ValidationError")
        human = body.get("human")
        if human is not None and not isinstance(human, bool):
            raise BoardError("human muss true oder false sein.", 400, "ValidationError")
        task = _board().update_task(g.principal, _ref(slug, number), title=body.get("title"),
                                    description=body.get("description"), tags=tags, status=body.get("status"),
                                    human=human, index=index)
        return jsonify(task_to_dict(task)), 200

    @app.delete("/board/projects/<slug>/tasks/<int:number>")
    def board_delete_task(slug: str, number: int):
        """Ticket loeschen (Freigabe-Recht)."""
        _board().delete_task(g.principal, _ref(slug, number))
        return "", 204

    @app.get("/board/projects/<slug>/tasks/<int:number>/comments")
    def board_list_comments(slug: str, number: int):
        """Kommentare eines Tickets mit Herkunft."""
        return jsonify({"comments": [comment_to_dict(c) for c in _board().comments(_ref(slug, number))]}), 200

    @app.post("/board/projects/<slug>/tasks/<int:number>/comments")
    def board_add_comment(slug: str, number: int):
        """Kommentar schreiben; die Herkunft kommt aus dem Token."""
        body = _json_object()
        comment = _board().add_comment(g.principal, _ref(slug, number), body.get("body"),
                                       author_name=body.get("author_name") or "")
        return jsonify(comment_to_dict(comment)), 201

    @app.get("/board/projects/<slug>/tasks/<int:number>/history")
    def board_history(slug: str, number: int):
        """Verlauf eines Tickets (Status, Titel, Beschreibung, Markierung)."""
        return jsonify({"history": [event_to_dict(e) for e in _board().history(_ref(slug, number))]}), 200

    @app.put("/board/comments/<comment_id>")
    def board_edit_comment(comment_id: str):
        """Eigenen Kommentar aendern (nur Mensch)."""
        comment = _board().edit_comment(g.principal, comment_id, _json_object().get("body"))
        return jsonify(comment_to_dict(comment)), 200

    @app.delete("/board/comments/<comment_id>")
    def board_delete_comment(comment_id: str):
        """Eigenen Kommentar loeschen (nur Mensch)."""
        _board().delete_comment(g.principal, comment_id)
        return "", 204

    @app.post("/board/import")
    def board_import():
        """JSON-Export eines Boards uebernehmen (Freigabe-Recht, idempotent)."""
        return jsonify(_board().import_export(g.principal, _json_object())), 200

    # ── Personal Export ─────────────────────────────────────────────────

    @app.get("/conversations/<conversation_id>/export")
    def export_conversation(conversation_id: str):
        result = handler.export_conversation(conversation_id)
        if not result.success:
            return jsonify({"error": result.message}), 404
        return jsonify(result.data), 200

    # ── Token Usage ────────────────────────────────────────────────────

    @app.get("/usage")
    def token_usage():
        result = handler.token_usage()
        return jsonify(result.data), 200

    @app.get("/usage/conversations")
    def conversation_usage():
        result = handler.conversation_usage()
        return jsonify(result.data), 200

    # ── Runs ───────────────────────────────────────────────────────────

    @app.get("/runs")
    def list_runs():
        conversation_id = request.args.get("conversation_id") or None
        try:
            limit = int(request.args.get("limit", 100))
        except ValueError:
            return jsonify({"error": "limit muss eine Zahl sein."}), 400
        result = handler.list_runs(conversation_id=conversation_id, limit=limit)
        if not result.success:
            return jsonify({"error": result.message}), 503
        return jsonify(result.data), 200

    @app.get("/runs/<run_id>")
    def get_run(run_id: str):
        result = handler.get_run(run_id)
        if not result.success:
            return jsonify({"error": result.message}), 404
        return jsonify(result.data), 200

    # ── Settings und Betrieb ───────────────────────────────────────────

    def _actual_port() -> int:
        """Tatsaechlich gebundener Port (vom WSGI-Server), sonst der konfigurierte."""
        configured = getattr(config, "port", 8000) if config else 8000
        try:
            return int(request.environ.get("SERVER_PORT") or configured)
        except (RuntimeError, ValueError):  # ausserhalb eines Requests / unlesbar
            return configured

    def _settings_payload() -> dict:
        fallback_keys = {
            "anthropic": getattr(config, "anthropic_api_key", "") if config else "",
            "openai": getattr(config, "openai_api_key", "") if config else "",
            "openai-responses": getattr(config, "openai_api_key", "") if config else "",
            "gemini": getattr(config, "gemini_api_key", "") if config else "",
        }
        from conclave.infrastructure.universal.presets import list_presets as _list_presets
        provider_keys = {}
        for preset in _list_presets():
            if not bool(preset.get("requires_api_key", True)):
                continue
            name = preset.get("name", "")
            key_env = preset.get("api_key_env", "")
            provider_keys[name] = bool(fallback_keys.get(name)) or bool(key_env and env_secret(key_env))

        return {
            "mode": getattr(config, "mode", "development") if config else "development",
            "host": getattr(config, "host", "127.0.0.1") if config else "127.0.0.1",
            "port": _actual_port(),
            "db_provider": getattr(config, "db_provider", "sqlite") if config else "sqlite",
            "db_path": str(getattr(config, "db_path", "")) if config else "",
            "workspace_path": WORKSPACE,
            "workspace_limits": {
                "ui_read_bytes": ui_read_limit_bytes(),
                "agent_read_bytes": agent_read_limit_bytes(),
                "write_bytes": write_limit_bytes(),
                "hidden_paths_visible": False,
            },
            "auth_required": bool(getattr(config, "api_key", "") if config else False),
            "rate_limit": {
                "value": rate_limit_state["value"],
                "source": rate_limit_state["source"],
                "active": _has_limiter and not rate_limit_disabled(rate_limit_state["value"]),
                "editable": rate_limit_state["source"] != "env",
                "persistent": bool(getattr(config, "config_path", None)),
            },
            "log_file": str(active_log_file() or ""),
            "provider_keys": provider_keys,
        }

    @app.get("/settings")
    def get_settings():
        """Gibt lokale Runtime-Settings ohne Secrets zurueck."""
        return jsonify({"settings": _settings_payload()}), 200

    @app.put("/settings")
    def update_settings():
        """Aktualisiert einfache Runtime-Settings fuer die laufende Session."""
        nonlocal WORKSPACE
        body = request.get_json() or {}
        workspace_path = body.get("workspace_path")
        if workspace_path is not None:
            workspace_path = str(workspace_path).strip()
            if not workspace_path:
                return jsonify({"error": "workspace_path darf nicht leer sein."}), 400
            WORKSPACE = workspace_path
            os.environ["CONCLAVE_WORKSPACE"] = workspace_path
            os.makedirs(WORKSPACE, exist_ok=True)
        if "rate_limit" in body:
            error = _update_rate_limit(body.get("rate_limit"))
            if error:
                return jsonify({"error": error[0], "type": error[1]}), error[2]
        return jsonify({"settings": _settings_payload()}), 200

    def _update_rate_limit(value):
        """Setzt das Rate-Limit sofort und speichert es in config.toml (falls bekannt)."""
        if rate_limit_state["source"] == "env":
            return ("Rate-Limit ist durch CONCLAVE_RATE_LIMIT festgelegt und hier nicht aenderbar.",
                    "RateLimitLocked", 409)
        value = str(value or "").strip()
        problem = validate_rate_limit(value) if value else "Rate-Limit darf nicht leer sein (zum Abschalten: off)."
        if problem:
            return (problem, "InvalidRateLimit", 400)
        config_path = getattr(config, "config_path", None)
        if config_path:
            try:
                set_toml_string(pathlib.Path(config_path), "server", "rate_limit", value)
            except (OSError, ValueError) as exc:
                logger.error("config.toml nicht aktualisiert: %s", exc)
                return ("Rate-Limit konnte nicht in config.toml gespeichert werden.", "ConfigWriteFailed", 500)
        rate_limit_state.update(value=value, source="config" if config_path else "session")
        if config is not None:
            config.rate_limit = value
        logger.info("Rate-Limit geaendert: %s", value)
        return None

    @app.get("/logs")
    def get_logs():
        """Letzte Eintraege der Server-Logdatei (fuer die Settings-Seite)."""
        path = active_log_file()
        if path is None or not path.is_file():
            return jsonify({"available": False, "log_file": str(path or ""), "entries": [],
                            "hint": "Keine Logdatei aktiv (Server ohne Datei-Logging gestartet)."}), 200
        try:
            limit = max(1, min(int(request.args.get("limit", 200)), 1000))
        except ValueError:
            return jsonify({"error": "limit muss eine Zahl sein."}), 400
        level = request.args.get("level", "DEBUG").upper()
        if level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            return jsonify({"error": "level muss DEBUG, INFO, WARNING, ERROR oder CRITICAL sein."}), 400
        return jsonify({"available": True, "log_file": str(path),
                        "entries": read_log_tail(path, limit=limit, min_level=level)}), 200

    def _backup_root() -> pathlib.Path:
        backup_root_env = os.environ.get("CONCLAVE_BACKUP_DIR", "").strip()
        if backup_root_env:
            return pathlib.Path(backup_root_env)
        if config and getattr(config, "db_provider", "sqlite") == "sqlite":
            return pathlib.Path(config.db_path).parent / "backups"
        return pathlib.Path(WORKSPACE).parent / "backups"

    def _sqlite_db_path() -> pathlib.Path | None:
        if config and getattr(config, "db_provider", "sqlite") == "sqlite":
            return pathlib.Path(config.db_path)
        return None

    def _resolve_backup_name(name) -> pathlib.Path | None:
        """Nur ein Dateiname (*.zip) direkt im Backup-Verzeichnis, keine Pfade (B4)."""
        if not isinstance(name, str) or not name.lower().endswith(".zip"):
            return None
        if any(sep in name for sep in ("/", "\\", ":")) or name in (".", ".."):
            return None
        root = _backup_root().resolve()
        path = (root / name).resolve()
        try:
            path.relative_to(root)
        except ValueError:  # z. B. Symlink nach aussen
            return None
        return path

    @app.post("/backup")
    def create_backup():
        """Erstellt ein lokales ZIP-Backup von SQLite-DB und Workspace."""
        backup_path = create_backup_archive(
            db_path=_sqlite_db_path(),
            workspace_root=pathlib.Path(WORKSPACE),
            backup_dir=_backup_root(),
        )
        return jsonify({"backup": backup_path.name, "backup_path": str(backup_path), "format": "zip"}), 201

    @app.get("/backups")
    def list_backups():
        """Listet die ZIP-Backups im Backup-Verzeichnis (neueste zuerst)."""
        root = _backup_root()
        files = sorted(root.glob("*.zip"), key=lambda f: f.stat().st_mtime, reverse=True) if root.is_dir() else []
        return jsonify({
            "backup_dir": str(root),
            "backups": [{
                "name": f.name,
                "size_bytes": f.stat().st_size,
                "modified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(f.stat().st_mtime)),
            } for f in files if f.is_file()],
        }), 200

    @app.post("/restore")
    def restore_backup():
        """Stellt SQLite-DB und Workspace aus einem ZIP-Backup im Backup-Verzeichnis wieder her."""
        body = request.get_json() or {}
        if "backup_path" in body:
            return jsonify({
                "error": "backup_path wird nicht mehr unterstuetzt. Dateinamen aus GET /backups als 'backup' uebergeben.",
                "status": "invalid_request",
            }), 400
        if not body.get("backup"):
            return jsonify({"error": "backup ist erforderlich (Dateiname aus GET /backups).", "status": "invalid_request"}), 400
        path = _resolve_backup_name(body.get("backup"))
        if path is None:
            return jsonify({"error": "Ungueltiger Backup-Name. Erlaubt ist nur ein Dateiname aus GET /backups.",
                            "status": "invalid_request"}), 400
        if not path.is_file():
            return jsonify({"error": "Backup nicht gefunden."}), 404
        replace_workspace = body.get("replace_workspace", False)
        if not isinstance(replace_workspace, bool):
            return jsonify({"error": "replace_workspace muss true oder false sein.", "status": "invalid_request"}), 400
        if replace_workspace and body.get("confirm") != "replace-workspace":
            return jsonify({
                "error": "Workspace leeren nur mit confirm: \"replace-workspace\".",
                "status": "confirmation_required",
            }), 400
        try:
            result = restore_backup_archive(
                backup_path=path,
                db_path=_sqlite_db_path(),
                workspace_root=pathlib.Path(WORKSPACE),
                backup_dir=_backup_root(),
                replace_workspace=replace_workspace,
            )
        except ValueError as exc:
            return jsonify({"error": str(exc), "status": "invalid_backup"}), 400
        except OSError as exc:
            logger.exception("Restore fehlgeschlagen: %s", exc)
            return jsonify({"error": "Restore fehlgeschlagen.", "status": "restore_failed"}), 500
        return jsonify({
            "status": "restored",
            "format": "zip",
            "db_restored": result.db_restored,
            "workspace_files_restored": result.workspace_files_restored,
            "workspace_replaced": result.workspace_replaced,
            "pre_restore_backup_path": str(result.pre_restore_backup_path),
        }), 200

    # ── Workspace (Dateisystem) ──────────────────────────────────────

    @app.get("/workspace")
    def list_workspace():
        """Listet alle Dateien im Workspace."""
        workspace_root_path = pathlib.Path(WORKSPACE)
        limits = {
            "ui_read_bytes": ui_read_limit_bytes(),
            "agent_read_bytes": agent_read_limit_bytes(),
            "write_bytes": write_limit_bytes(),
        }
        if not workspace_root_path.is_dir():
            return jsonify({"files": [], "limits": limits}), 200
        files = []
        for root, dirs, fnames in os.walk(WORKSPACE):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in fnames:
                path = os.path.join(root, f)
                if is_hidden_workspace_path(pathlib.Path(path), root=workspace_root_path):
                    continue
                rel = os.path.relpath(path, WORKSPACE).replace("\\", "/")
                files.append({
                    "path": rel,
                    "size": os.path.getsize(path),
                    "modified": os.path.getmtime(path),
                })
        files.sort(key=lambda x: x["path"])
        return jsonify({
            "files": files,
            "limits": limits,
        }), 200

    @app.get("/workspace/<path:filepath>")
    def read_workspace_file(filepath: str):
        """Liest eine Datei aus dem Workspace."""
        resolved = resolve_workspace_path(filepath, root=pathlib.Path(WORKSPACE))
        if resolved is None:
            return jsonify({"error": "Pfad nicht erlaubt"}), 403
        if not resolved.path.is_file():
            return jsonify({"error": "Datei nicht gefunden"}), 404
        if is_hidden_workspace_path(resolved.path, root=resolved.root):
            return jsonify({"error": "Datei nicht gefunden"}), 404
        if not assert_size_allowed(resolved.path, ui_read_limit_bytes()):
            return jsonify({"error": "Datei zu gross", "limit_bytes": ui_read_limit_bytes()}), 413
        try:
            with open(resolved.path, "r", encoding="utf-8") as fh:
                content = fh.read()
            return jsonify({"path": resolved.relative, "content": content}), 200
        except UnicodeDecodeError:
            return jsonify({"error": "Binaerdatei nicht lesbar"}), 415

    @app.post("/workspace/<path:filepath>")
    def write_workspace_file(filepath: str):
        """Schreibt eine Datei in den Workspace."""
        resolved = resolve_workspace_path(filepath, root=pathlib.Path(WORKSPACE))
        if resolved is None:
            return jsonify({"error": "Pfad nicht erlaubt"}), 403
        if is_hidden_workspace_path(resolved.path, root=resolved.root):
            return jsonify({"error": "Pfad nicht erlaubt"}), 403
        body = request.get_json() or {}
        content = body.get("content", "")
        if text_size(str(content)) > write_limit_bytes():
            return jsonify({"error": "Datei zu gross", "limit_bytes": write_limit_bytes()}), 413
        os.makedirs(os.path.dirname(resolved.path), exist_ok=True)
        with open(resolved.path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return jsonify({"path": resolved.relative, "size": len(content)}), 201

    @app.delete("/workspace/<path:filepath>")
    def delete_workspace_file(filepath: str):
        """Loescht eine Datei aus dem Workspace."""
        resolved = resolve_workspace_path(filepath, root=pathlib.Path(WORKSPACE))
        if resolved is None:
            return jsonify({"error": "Pfad nicht erlaubt"}), 403
        if is_hidden_workspace_path(resolved.path, root=resolved.root):
            return jsonify({"error": "Pfad nicht erlaubt"}), 403
        if not resolved.path.is_file():
            return jsonify({"error": "Datei nicht gefunden"}), 404
        os.remove(resolved.path)
        return "", 204

    return app
