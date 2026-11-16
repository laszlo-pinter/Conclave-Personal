# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Laszlo Pinter

"""Basis der Fehler und Schwaerzung von Fehlertexten (gemeinsam fuer Board und Personal)."""

import re


class ConclaveError(Exception):
    """Basis-Exception fuer alle Conclave-Domain-Fehler.

    Alle spezifischen Fehler erben von dieser Klasse.
    API-Layer mappt sie auf HTTP-Statuscodes.
    """


class AuthenticationError(ConclaveError):
    """Authentifizierung fehlgeschlagen."""
    def __init__(self, message: str = "Invalid or missing authentication token."):
        super().__init__(message)


# ── Fehlertexte fuer Clients und Logs ───────────────────────────────────

_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s'\"<>]+", re.IGNORECASE)
_SECRETS = (
    (re.compile(r"(?i)\b(key|api_key|apikey|token|access_token|secret)=[^&\s'\"]+"), r"\1=***"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer ***"),
    (re.compile(r"\b(?:sk|cva|cvh|cvr)[-_][A-Za-z0-9_-]{6,}"), "***"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"), "***"),
)


def redact_secrets(text: str, *, urls: bool = True) -> str:
    """Schwaerzt Keys (und URLs) in einem Fehlertext."""
    text = str(text)
    for pattern, replacement in _SECRETS:
        text = pattern.sub(replacement, text)
    return _URL.sub("<url>", text) if urls else text


def public_message(exc: BaseException) -> str:
    """Text eines Fehlers fuer Clients: eigene Meldungen geschwaerzt, fremde nur mit Typ."""
    if isinstance(exc, (ConclaveError, ValueError)) or type(exc).__module__.startswith("httpx"):
        return redact_secrets(str(exc))
    return f"Interner Fehler ({type(exc).__name__}), Details im Server-Log."
