# src/conclave/api/app.py

import json as _json
import os
import time

try:
    from flask import Flask, Response, jsonify, request, stream_with_context, send_file as flask_send_file
    from werkzeug.exceptions import HTTPException
except ImportError:
    raise ImportError(
        "Das 'flask'-Paket ist nicht installiert. "
        "Bitte installieren mit: pip install conclave[api]"
    )

from conclave.cli.handler import CLIHandler
from conclave.domain.errors import (
    AdapterNotFound,
    AgentAlreadyExists,
    AgentNotFound,
    AuthenticationError,
    ConversationNotFound,
    FloorNotGranted,
    NoFloorGranted,
    ParticipantAlreadyRegistered,
    ParticipantNotRegistered,
)
from conclave.domain.participant import ParticipantType
from conclave.application.workspace_security import (
    agent_read_limit_bytes,
    assert_size_allowed,
    is_hidden_workspace_path,
    resolve_workspace_path,
    text_size,
    ui_read_limit_bytes,
    write_limit_bytes,
)
from conclave.infrastructure.log import get_logger
from conclave.runtime.assets import get_asset_root

try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    _has_limiter = True
except ImportError:
    _has_limiter = False

logger = get_logger("api")


def create_app(handler: CLIHandler, auth_service=None,
               agent_service=None, config=None, service=None) -> Flask:
    import pathlib
    asset_root = get_asset_root()
    app = Flask(__name__, static_folder=str(asset_root / "static"), static_url_path="/static")
    WORKSPACE = os.environ.get("CONCLAVE_WORKSPACE", "/workspace")

    def _refresh_registry():
        """Invalidiert den Adapter-Cache — Lazy Builder baut bei Bedarf neu."""
        if service and hasattr(service, '_registry') and service._registry:
            service._registry.invalidate()

    if _has_limiter:
        limiter = Limiter(get_remote_address, app=app, default_limits=["120 per minute"],
                          storage_uri="memory://")

    @app.before_request
    def _authenticate():
        if request.method == "OPTIONS":
            return
        if auth_service is None:
            return
        token = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        else:
            token = request.headers.get("X-API-Key")
        if not auth_service.validate_token(token):
            raise AuthenticationError()
        # RBAC: nur wenn der AuthService Rollen-Pruefung unterstuetzt
        if hasattr(auth_service, "check_permission") and hasattr(auth_service, "get_role"):
            role = auth_service.get_role(token) or ""
            if not auth_service.check_permission(role, request.method, request.path):
                return jsonify({"error": "Forbidden", "type": "PermissionDenied"}), 403

    @app.before_request
    def _log_request_start():
        request._start_time = time.monotonic()
        logger.debug("request start: %s %s", request.method, request.path)

    @app.after_request
    def _log_request_end(response):
        duration_ms = (time.monotonic() - getattr(request, "_start_time", time.monotonic())) * 1000
        logger.info(
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
        # CORS: nur explizit konfigurierte Origins, kein Wildcard-Reflect
        origin = request.headers.get("Origin", "")
        if origin and origin in _cors_allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-API-Key"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        return response

    @app.route("/", defaults={"path": ""}, methods=["OPTIONS"])
    @app.route("/<path:path>", methods=["OPTIONS"])
    def _cors_preflight(path):
        return "", 204

    # ── UI Serving ────────────────────────────────────────────────────────

    def _notify_new_message(conversation_id: str, sequence: int, author: str = ""):
        """Schreibt eine Marker-Datei bei neuer Nachricht (fuer FileChanged Hook)."""
        workspace = os.environ.get("CONCLAVE_WORKSPACE", "/workspace")
        marker = pathlib.Path(workspace) / "conclave_notify.json"
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

    @app.post("/guard/notify")
    def guard_notify():
        """Leitet eine Benachrichtigung an den Guard-Service weiter.

        Guard laeuft auf dem Host (nicht im Container).
        CD kann auch direkt http://localhost:5001/notify aufrufen.
        """
        body = request.get_json() or {}
        guard_url = os.environ.get("GUARD_URL", "http://host.docker.internal:5001")
        try:
            import urllib.request as _urlreq
            data = _json.dumps(body).encode()
            req = _urlreq.Request(f"{guard_url}/notify", data=data,
                                  headers={"Content-Type": "application/json"}, method="POST")
            with _urlreq.urlopen(req, timeout=10) as resp:
                result = _json.loads(resp.read())
            return jsonify(result), resp.status
        except Exception as e:
            return jsonify({
                "error": f"Guard nicht erreichbar: {e}",
                "hint": "Guard direkt erreichbar unter http://localhost:5001/notify"
            }), 502

    @app.get("/api-docs")
    def swagger_ui():
        """Swagger UI — interaktive API-Dokumentation."""
        return """<!DOCTYPE html>
<html><head>
<title>Conclave API</title>
<link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
</head><body>
<div id="swagger-ui"></div>
<script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>SwaggerUIBundle({url:'/static/openapi.json',dom_id:'#swagger-ui',deepLinking:true})</script>
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

    # ── Error Handler ────────────────────────────────────────────────────

    def _error_json(e: Exception, status: int):
        return jsonify({"error": str(e), "type": type(e).__name__}), status

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

    @app.errorhandler(FloorNotGranted)
    def _handle_floor_not_granted(e):
        return _error_json(e, 409)

    @app.errorhandler(AdapterNotFound)
    def _handle_adapter_not_found(e):
        return _error_json(e, 502)

    @app.errorhandler(ValueError)
    def _handle_value_error(e):
        return _error_json(e, 400)

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
                created_at=created_at,
            )
        except (ValueError, Exception) as e:
            return jsonify({"error": str(e)}), 400
        result = handler.update_agent(agent)
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
                or bool(key_env and os.environ.get(key_env))
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
            return jsonify({"error": result.message}), 409
        return jsonify(result.data), 200

    # ── GET /conversations/<id> ──────────────────────────────────────────

    @app.get("/conversations/<conversation_id>")
    def get_conversation(conversation_id: str):
        result = handler.show_conversation(conversation_id)
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
            return jsonify({"error": "participant_id und name sind erforderlich."}), 400

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

        result = handler.add_message(conversation_id, content)
        if not result.success:
            return jsonify({"error": result.message}), 404
        return jsonify(result.data), 201

    # ── POST /conversations/<id>/participants/<pid>/invoke ───────────────

    @app.post("/conversations/<conversation_id>/participants/<participant_id>/invoke")
    def invoke_participant(conversation_id: str, participant_id: str):
        body = request.get_json(silent=True) or {}
        judge_via = body.get("judge_via")

        if judge_via:
            judge_prompt = body.get("judge_prompt")
            if not judge_prompt or not isinstance(judge_prompt, str):
                return jsonify({"error": "judge_prompt (string) ist erforderlich wenn judge_via gesetzt ist."}), 400
            result = handler.invoke_with_judge(conversation_id, participant_id, judge_via, judge_prompt)
            # Partial success: Primary erfolgreich, Judge fehlgeschlagen -> 200 mit judge.error im body
            if not result.success and "content" in (result.data or {}):
                return jsonify(result.data), 200
            if not result.success:
                return jsonify({"error": result.message}), 502
            return jsonify(result.data), 200

        result = handler.invoke_participant(conversation_id, participant_id)
        if not result.success:
            return jsonify({"error": result.message}), 502
        return jsonify(result.data), 200

    # ── POST /conversations/<id>/orchestrate ─────────────────────────────

    @app.post("/conversations/<conversation_id>/orchestrate")
    def orchestrate(conversation_id: str):
        body = request.get_json() or {}
        sequence = body.get("sequence")
        if not sequence or not isinstance(sequence, list):
            return jsonify({"error": "sequence (Liste von participant_ids) ist erforderlich."}), 400

        result = handler.orchestrate(conversation_id, sequence)
        if not result.success:
            return jsonify({"error": result.message}), 502
        return jsonify(result.data), 200

    # ── POST /conversations/<id>/orchestrate-parallel ─────────────────────

    @app.post("/conversations/<conversation_id>/orchestrate-parallel")
    def orchestrate_parallel(conversation_id: str):
        body = request.get_json() or {}
        groups = body.get("groups")
        if not groups or not isinstance(groups, list):
            return jsonify({"error": "groups (Liste von Listen mit participant_ids) ist erforderlich."}), 400

        result = handler.orchestrate_parallel(conversation_id, groups)
        if not result.success:
            return jsonify({"error": result.message}), 502
        return jsonify(result.data), 200

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
        sequence = body.get("sequence")
        if not sequence or not isinstance(sequence, list) or len(sequence) == 0:
            return jsonify({
                "error": "sequence (nicht-leere Liste von participant_ids) ist erforderlich."
            }), 400

        stop_signal = body.get("stop_signal", "@done")
        max_rounds = int(body.get("max_rounds", 20))

        def generate():
            try:
                for event in handler.auto_loop(
                    conversation_id=conversation_id,
                    sequence=sequence,
                    stop_signal=stop_signal,
                    max_rounds=max_rounds,
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

    # ── Personal Export ─────────────────────────────────────────────────

    @app.get("/conversations/<conversation_id>/export")
    def export_conversation(conversation_id: str):
        result = handler.export_conversation(conversation_id)
        if not result.success:
            return jsonify({"error": result.message}), 404
        return jsonify(result.data), 200

    @app.post("/conversations/<conversation_id>/judge")
    def judge(conversation_id: str):
        """Fuehrt Primary + Judge als expliziten Personal-API-Flow aus."""
        body = request.get_json() or {}
        primary_id = body.get("primary_id")
        judge_id = body.get("judge_id")
        judge_prompt = body.get("judge_prompt")
        if not primary_id or not judge_id or not judge_prompt:
            return jsonify({"error": "primary_id, judge_id und judge_prompt sind erforderlich."}), 400
        result = handler.invoke_with_judge(conversation_id, primary_id, judge_id, judge_prompt)
        if not result.success and "content" in (result.data or {}):
            return jsonify(result.data), 200
        if not result.success:
            return jsonify({"error": result.message}), 502
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

    def _settings_payload() -> dict:
        return {
            "mode": getattr(config, "mode", "development") if config else "development",
            "host": getattr(config, "host", "127.0.0.1") if config else "127.0.0.1",
            "port": getattr(config, "port", 8000) if config else 8000,
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
            "provider_keys": {
                "anthropic": bool(getattr(config, "anthropic_api_key", "") if config else ""),
                "openai": bool(getattr(config, "openai_api_key", "") if config else ""),
                "gemini": bool(getattr(config, "gemini_api_key", "") if config else ""),
            },
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
        return jsonify({"settings": _settings_payload()}), 200

    @app.post("/backup")
    def create_backup():
        """Erstellt ein lokales ZIP-Backup von SQLite-DB und Workspace."""
        import zipfile
        from datetime import datetime, timezone

        backup_root_env = os.environ.get("CONCLAVE_BACKUP_DIR", "").strip()
        backup_root = pathlib.Path(backup_root_env) if backup_root_env else None
        if backup_root is None:
            if config and getattr(config, "db_provider", "sqlite") == "sqlite":
                backup_root = pathlib.Path(config.db_path).parent / "backups"
            else:
                backup_root = pathlib.Path(WORKSPACE).parent / "backups"
        backup_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = backup_root / f"conclave-backup-{stamp}.zip"
        with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            if config and getattr(config, "db_provider", "sqlite") == "sqlite":
                db_path = pathlib.Path(config.db_path)
                if db_path.is_file():
                    zf.write(db_path, "conclave.db")
            workspace = pathlib.Path(WORKSPACE)
            if workspace.is_dir():
                for path in workspace.rglob("*"):
                    if path.is_file():
                        zf.write(path, pathlib.PurePosixPath("workspace", *path.relative_to(workspace).parts))
        return jsonify({"backup_path": str(backup_path), "format": "zip"}), 201

    @app.post("/restore")
    def restore_backup():
        """Validate Backup: prueft ein Archiv, schreibt aber keine lokalen Daten."""
        body = request.get_json() or {}
        backup_path = body.get("backup_path")
        if not backup_path:
            return jsonify({"error": "backup_path ist erforderlich."}), 400
        path = pathlib.Path(str(backup_path))
        if not path.is_file():
            return jsonify({"error": "Backup nicht gefunden."}), 404
        return jsonify({
            "status": "not_implemented",
            "message": "Backup-Validierung ist vorbereitet; Restore schreibt in v0.1.0 keine lokalen Daten.",
        }), 501

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
