"""Frei waehlbare IDs (Agenten, Participants) landen in URL-Pfaden (UI, MCP).

Nur sichere Zeichen, kein "." oder ".." (R4). Die Regel gilt in API und Diensten (R15).
"""

import re

_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,64}\Z")
ID_RULE_ERROR = "ID: 1-64 Zeichen aus A-Z, a-z, 0-9, Punkt, Bindestrich und Unterstrich; nicht '.' oder '..'."


def valid_id(value) -> bool:
    return isinstance(value, str) and bool(_ID_RE.match(value)) and value not in (".", "..")


def require_valid_id(value) -> None:
    """ValueError, wenn ``value`` keine sichere ID ist."""
    if not valid_id(value):
        raise ValueError(ID_RULE_ERROR)
