# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Laszlo Pinter

"""Versionen der Board-API (T3): Praefixe, Abkuendigung des Alias, Angabe fuer /board/versions und /health."""

V1_PREFIX = "/board/v1"
ALIAS_PREFIX = "/board"
PREFIXES = (V1_PREFIX, ALIAS_PREFIX)
VERSIONS_PATH = "/board/versions"
# Alias /board: abgekuendigt am 17.11.2026 (RFC 9745), entfaellt fruehestens zum 1.3.2027 (RFC 8594);
# Plan 7: mindestens ein Minor-Release und 3 Monate parallel
ALIAS_DEPRECATION = "@1794873600"
ALIAS_SUNSET = "Mon, 01 Mar 2027 00:00:00 GMT"


def board_versions() -> dict:
    """Was ``GET /board/versions`` und ``/health`` ueber die Board-API sagen."""
    return {
        "current": "v1",
        "versions": [{"version": "v1", "path": V1_PREFIX, "status": "stable"}],
        "deprecated": [{"path": ALIAS_PREFIX, "successor": V1_PREFIX, "sunset": ALIAS_SUNSET}],
    }
