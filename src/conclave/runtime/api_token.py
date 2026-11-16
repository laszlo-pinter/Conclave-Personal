"""Lokales API-Token (AP 2 / B2).

Die API verlangt immer ein Token. Ist ``CONCLAVE_API_KEY`` nicht gesetzt,
erzeugt der Server beim ersten Start ein zufaelliges Token und legt es in
``api.token`` im Konfigurationsverzeichnis ab (neben ``secret.key``).
CLI-Werkzeuge (web, desktop, watch) lesen es von dort, wenn die Variable fehlt.

Daneben gibt es ein Agent-Token (``CONCLAVE_AGENT_KEY`` bzw. ``agent.token``),
das genauso angelegt wird. Der MCP-Server nutzt nur dieses, nie ``api.token``.
Der automatische Reviewer hat ein eigenes Token (``CONCLAVE_REVIEWER_KEY`` bzw.
``reviewer.token``, P3). Neue Tokens tragen ein Praefix (``cvh_`` Mensch,
``cva_`` Agent, ``cvr_`` Reviewer); vorhandene Tokens ohne Praefix bleiben gueltig.
Tokens werden nie geloggt, nur Pfade.
"""

import os
import secrets
from pathlib import Path

from conclave.infrastructure.log import get_logger
from conclave.runtime.env import env_secret
from conclave.runtime.paths import get_runtime_paths

logger = get_logger("runtime.api_token")

TOKEN_FILE_NAME = "api.token"
AGENT_TOKEN_FILE_NAME = "agent.token"
REVIEWER_TOKEN_FILE_NAME = "reviewer.token"
HUMAN_PREFIX = "cvh_"
AGENT_PREFIX = "cva_"
REVIEWER_PREFIX = "cvr_"


def _path(override_env: str, file_name: str) -> Path:
    override = os.environ.get(override_env, "").strip()
    if override:
        return Path(override).expanduser()
    return get_runtime_paths().config_dir / file_name


def token_path() -> Path:
    return _path("CONCLAVE_API_TOKEN_FILE", TOKEN_FILE_NAME)


def agent_token_path() -> Path:
    return _path("CONCLAVE_AGENT_TOKEN_FILE", AGENT_TOKEN_FILE_NAME)


def reviewer_token_path() -> Path:
    return _path("CONCLAVE_REVIEWER_TOKEN_FILE", REVIEWER_TOKEN_FILE_NAME)


def _read(env_name: str, path: Path) -> str:
    env_key = env_secret(env_name)
    if env_key:
        return env_key
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def read_token() -> str:
    """Mensch-Token fuer Clients: ``CONCLAVE_API_KEY``, sonst Token-Datei, sonst leer."""
    return _read("CONCLAVE_API_KEY", token_path())


def read_agent_token() -> str:
    """Agent-Token fuer Clients: ``CONCLAVE_AGENT_KEY``, sonst ``agent.token``, sonst leer."""
    return _read("CONCLAVE_AGENT_KEY", agent_token_path())


def read_reviewer_token() -> str:
    """Reviewer-Token fuer den Reviewer-MCP: ``CONCLAVE_REVIEWER_KEY``, sonst ``reviewer.token``."""
    return _read("CONCLAVE_REVIEWER_KEY", reviewer_token_path())


def load_or_create_reviewer_token(path: Path | None = None) -> str:
    """Reviewer-Token fuer den Server: vorhandene Datei lesen oder neues Token anlegen."""
    return load_or_create_token(path or reviewer_token_path(), prefix=REVIEWER_PREFIX)


def load_or_create_agent_token(path: Path | None = None) -> str:
    """Agent-Token fuer den Server: vorhandene Datei lesen oder neues Token anlegen."""
    return load_or_create_token(path or agent_token_path(), prefix=AGENT_PREFIX)


def load_or_create_token(path: Path | None = None, prefix: str = HUMAN_PREFIX) -> str:
    """Token fuer den Server: vorhandene Datei lesen oder neues Token anlegen."""
    from conclave.runtime.file_security import create_exclusive, harden, replace_private

    path = path or token_path()
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
