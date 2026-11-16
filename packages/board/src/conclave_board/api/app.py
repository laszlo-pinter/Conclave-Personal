# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Laszlo Pinter

"""App-Fabrik nur fuer das Board (T1): REST-API ohne Oberflaeche.

Dieselben Schutzregeln wie in Personal, beschraenkt auf die Board-Routen:

- Host-Allowlist gegen DNS-Rebinding (B2)
- POST nur mit JSON oder eigenem Client-Header (B3)
- Anmeldung fuer jede Route ausser ``/health`` (B12); die Rolle kommt allein aus dem Token
- Agent und Reviewer nur auf ihren Allowlists (Default deny, Z2, P3)
- Rate-Limit je Zugang und IP, eigenes Limit fuer Agenten (R11)
- Groessenlimit je Anfrage, eigene Grenze fuer den Import (R6)
- Sicherheits-Header; Fehlertexte ohne Keys und URLs

Die Token-Pruefung ist eine Schnittstelle (``Authenticator``): Heute haengt
Personal und der Board-Server ``StaticKeyAuthService`` mit drei festen Tokens
ein; Konten und Tokens pro Person folgen in T4.
"""

from __future__ import annotations

import logging
import time
from typing import Protocol

from flask import Flask, g, jsonify, request
from werkzeug.exceptions import HTTPException

from conclave_board import __version__
from conclave_board.api.access import (
    BOARD_AGENT_ALLOWED, BOARD_REVIEWER_ALLOWED, HUMAN_ONLY_ERROR, WHOAMI, may,
)
from conclave_board.api.routes import create_board_blueprint
from conclave_board.api.security import CLIENT_HEADER, MAX_REQUEST_BYTES, is_host_allowed, parse_allowed_hosts, request_token
from conclave_board.domain.errors import AuthenticationError, public_message
from conclave_board.domain.principal import HUMAN_PRINCIPAL, Principal
from conclave_board.infrastructure.log import get_logger

logger = get_logger("board.api")

PUBLIC_GET_PATHS = frozenset({"/health"})
AGENT_ALLOWED = BOARD_AGENT_ALLOWED | WHOAMI
REVIEWER_ALLOWED = BOARD_REVIEWER_ALLOWED | WHOAMI

DEFAULT_RATE_LIMIT = "300 per minute"
DEFAULT_AGENT_RATE_LIMIT = "60 per minute"

# Nur JSON, kein Browser-Inhalt: nichts laden, nicht einbetten
CONTENT_SECURITY_POLICY = "default-src 'none'; frame-ancestors 'none'"


class Authenticator(Protocol):
    """Schnittstelle der Token-Pruefung: Rolle zum Token oder ``None``."""

    def authenticate(self, token: str | None) -> Principal | None: ...


def _limit_off(value: str | None) -> bool:
    return (value or "").strip().lower() in ("off", "none", "0", "")


def create_board_app(board, auth_service: Authenticator | None, *, allowed_hosts: str = "",
                     rate_limit: str = DEFAULT_RATE_LIMIT, agent_rate_limit: str = DEFAULT_AGENT_RATE_LIMIT,
                     allow_unauthenticated: bool = False) -> Flask:
    """Baut die Board-App. Ohne ``auth_service`` nur mit ``allow_unauthenticated=True`` (Tests)."""
    if auth_service is None and not allow_unauthenticated:
        raise ValueError("create_board_app braucht einen auth_service; ohne Anmeldung nur mit "
                         "allow_unauthenticated=True (Tests).")
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
    hosts = parse_allowed_hosts(allowed_hosts)

    def _principal() -> Principal | None:
        if auth_service is None:
            return HUMAN_PRINCIPAL
        return auth_service.authenticate(request_token(request.headers))

    def _role() -> str:
        principal = _principal()
        return principal.role if principal is not None else "anonymous"

    try:
        from flask_limiter import Limiter
        from flask_limiter.util import get_remote_address
    except ImportError:          # Abhaengigkeit des Pakets; ohne sie kein Start
        raise ImportError("Das Paket 'flask-limiter' fehlt (Abhaengigkeit von conclave-board).") from None

    def _current_limit() -> str:
        if _role() in ("agent", "reviewer") and not _limit_off(agent_rate_limit):
            return agent_rate_limit
        return DEFAULT_RATE_LIMIT if _limit_off(rate_limit) else rate_limit

    def _exempt() -> bool:
        if _role() in ("agent", "reviewer") and not _limit_off(agent_rate_limit):
            return False
        return _limit_off(rate_limit)

    Limiter(lambda: f"{_role()}:{get_remote_address()}", app=app, default_limits=[_current_limit],
            default_limits_exempt_when=_exempt, storage_uri="memory://")

    @app.before_request
    def _check_host():
        if not is_host_allowed(request.host, hosts):
            return jsonify({"error": "Host nicht erlaubt.", "type": "InvalidHost"}), 421

    @app.before_request
    def _check_content_type():
        if request.method != "POST" or request.routing_exception is not None:
            return
        if request.mimetype == "application/json" or CLIENT_HEADER in request.headers:
            return
        return jsonify({"error": f"Content-Type application/json oder Header {CLIENT_HEADER} erforderlich.",
                        "type": "UnsupportedMediaType"}), 415

    @app.before_request
    def _authenticate():
        if request.method in ("GET", "HEAD") and request.path in PUBLIC_GET_PATHS:
            return
        principal = _principal()
        if principal is None:
            raise AuthenticationError()
        g.principal = principal

    @app.before_request
    def _check_agent_access():
        principal = g.get("principal")
        if principal is None or not principal.is_agent or request.url_rule is None:
            return
        allowed = REVIEWER_ALLOWED if principal.is_reviewer else AGENT_ALLOWED
        if not may(allowed, request.method, request.url_rule.rule):
            return jsonify(HUMAN_ONLY_ERROR), 403

    @app.before_request
    def _start_timer():
        g.request_start = time.monotonic()

    @app.after_request
    def _finish(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        duration_ms = (time.monotonic() - g.get("request_start", time.monotonic())) * 1000
        quiet = request.method in ("GET", "HEAD") and response.status_code < 400
        logger.log(logging.DEBUG if quiet else logging.INFO, "%s %s → %d (%.1f ms)",
                   request.method, request.path, response.status_code, duration_ms,
                   extra={"method": request.method, "path": request.path,
                          "status": response.status_code, "duration_ms": duration_ms})
        return response

    @app.errorhandler(AuthenticationError)
    def _unauthenticated(e):
        return jsonify({"error": public_message(e), "type": "AuthenticationError"}), 401

    @app.errorhandler(413)
    def _too_large(e):
        return jsonify({"error": f"Anfrage zu gross (hoechstens {MAX_REQUEST_BYTES // (1024 * 1024)} MB).",
                        "type": "RequestTooLarge"}), 413

    @app.errorhandler(429)
    def _rate_limited(e):
        return jsonify({"error": f"Zu viele Anfragen ({e.description}).", "type": "RateLimitExceeded"}), 429

    @app.errorhandler(ValueError)
    def _invalid(e):
        return jsonify({"error": public_message(e), "type": "ValueError"}), 400

    @app.errorhandler(HTTPException)
    def _http(e):
        return jsonify({"error": e.description, "type": type(e).__name__}), e.code

    @app.errorhandler(Exception)
    def _unexpected(e):
        logger.exception("Unhandled exception: %s", e)
        return jsonify({"error": "Internal server error", "type": "InternalError"}), 500

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "product": "conclave-board", "version": __version__}), 200

    @app.get("/auth/whoami")
    def whoami():
        return jsonify({"role": g.principal.role}), 200

    app.register_blueprint(create_board_blueprint(board))
    return app
