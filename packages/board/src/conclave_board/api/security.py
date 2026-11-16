# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Laszlo Pinter

"""Gemeinsame Schutzregeln der HTTP-API: Host-Allowlist, Groessen, Token aus der Anfrage.

Board-App und Personal nutzen dieselben Regeln (T1).
"""

BOARD_IMPORT_MAX_BYTES = 50 * 1024 * 1024    # Groesse des JSON-Exports, vor dem Parsen geprueft
MAX_REQUEST_BYTES = 10 * 1024 * 1024         # alle anderen Anfragen (R6); der Import hat seine eigene Grenze

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


def request_token(headers) -> str | None:
    """Token aus ``Authorization: Bearer`` oder ``X-API-Key``."""
    auth_header = headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return headers.get("X-API-Key")
