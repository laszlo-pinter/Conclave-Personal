"""Secrets aus Umgebungsvariablen lesen.

Werden Keys ueber den Windows-Dialog "Umgebungsvariablen" gesetzt, landen leicht
Anfuehrungszeichen oder Leerzeichen im Wert (z. B. aus `$env:X = "sk-..."`).
Der Provider meldet dann nur "invalid API key". ``env_secret`` entfernt
umschliessende Leerzeichen und Anfuehrungszeichen und warnt einmal pro Variable
(nur der Name wird geloggt, nie der Wert).
"""

import logging
import os

logger = logging.getLogger("conclave.runtime.env")
_warned: set[str] = set()


def clean_secret(value: str) -> str:
    cleaned = (value or "").strip()
    while len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ("'", '"'):
        cleaned = cleaned[1:-1].strip()
    return cleaned


def env_secret(name: str, default: str = "") -> str:
    raw = os.environ.get(name)
    if raw is None:
        return default
    cleaned = clean_secret(raw)
    if cleaned != raw and name not in _warned:
        _warned.add(name)
        logger.warning("Umgebungsvariable %s enthielt Anfuehrungszeichen oder Leerzeichen - bereinigt", name)
    return cleaned
