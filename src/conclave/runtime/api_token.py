"""Lokales API-Token (AP 2 / B2).

Die API verlangt immer ein Token. Ist ``CONCLAVE_API_KEY`` nicht gesetzt,
erzeugt der Server beim ersten Start ein zufaelliges Token und legt es in
``api.token`` im Konfigurationsverzeichnis ab (neben ``secret.key``).
CLI-Werkzeuge und der MCP-Server lesen es von dort, wenn die Variable fehlt.
"""

import os
import secrets
import subprocess
from pathlib import Path

from conclave.infrastructure.log import get_logger
from conclave.runtime.env import env_secret
from conclave.runtime.paths import get_runtime_paths

logger = get_logger("runtime.api_token")

TOKEN_FILE_NAME = "api.token"


def token_path() -> Path:
    override = os.environ.get("CONCLAVE_API_TOKEN_FILE", "").strip()
    if override:
        return Path(override).expanduser()
    return get_runtime_paths().config_dir / TOKEN_FILE_NAME


def read_token() -> str:
    """Token fuer Clients: ``CONCLAVE_API_KEY``, sonst Token-Datei, sonst leer."""
    env_key = env_secret("CONCLAVE_API_KEY")
    if env_key:
        return env_key
    path = token_path()
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def load_or_create_token(path: Path | None = None) -> str:
    """Token fuer den Server: vorhandene Datei lesen oder neues Token anlegen."""
    path = path or token_path()
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        existing = ""
    if existing:
        return existing

    token = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token + "\n")
    _restrict_permissions(path)
    logger.info("API-Token erzeugt: %s", path)
    return token


def _restrict_permissions(path: Path) -> None:
    if os.name != "nt":
        path.chmod(0o600)
        return
    # Windows: geerbte Rechte entfernen, nur der aktuelle Benutzer behaelt Vollzugriff.
    user = os.environ.get("USERNAME", "")
    domain = os.environ.get("USERDOMAIN", "")
    if not user:
        logger.warning("ACL fuer %s nicht gesetzt: USERNAME unbekannt", path)
        return
    principal = f"{domain}\\{user}" if domain else user
    result = subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", f"{principal}:F"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        logger.warning("ACL fuer %s nicht gesetzt: %s", path, (result.stderr or result.stdout).strip())
