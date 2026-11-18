# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Laszlo Pinter

"""Token-Dateien anlegen und lesen (R13): exklusiv, nur fuer den Benutzer lesbar.

Neue Tokens tragen ein Praefix (``cvh_`` Mensch, ``cva_`` Agent, ``cvr_`` Reviewer);
vorhandene Tokens ohne Praefix bleiben gueltig. Tokens werden nie geloggt, nur Pfade.
"""

import secrets
from pathlib import Path

from conclave_board.infrastructure.log import get_logger

logger = get_logger("runtime.api_token")

HUMAN_PREFIX = "cvh_"
AGENT_PREFIX = "cva_"
REVIEWER_PREFIX = "cvr_"


def create_token_file(path: Path, prefix: str = HUMAN_PREFIX) -> str:
    """Token fuer den Server: vorhandene Datei lesen oder neues Token anlegen."""
    from conclave_board.runtime.file_security import create_exclusive, harden, replace_private

    try:
        existing = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        existing = None
    if existing:
        harden(path)                            # vorhandene Datei: fremde Rechte entfernen (R13)
        return existing

    data = (prefix + secrets.token_urlsafe(32) + "\n").encode("utf-8")
    if existing is None:
        # Exklusiv anlegen: bei gleichzeitigem Start gewinnt genau ein Token
        if create_exclusive(path, data):
            logger.info("Token erzeugt: %s", path)
    else:
        # Leere Datei (z. B. Absturz beim Schreiben): ersetzen statt mit leerem Token starten
        logger.warning("Token-Datei %s ist leer; neues Token erzeugt", path)
        replace_private(path, data)
    return path.read_text(encoding="utf-8").strip()
