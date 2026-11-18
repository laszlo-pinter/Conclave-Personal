"""Standardorte des Reviewers, ohne Import aus Conclave Personal (TR1).

Ohne Angabe gilt der Konfigurationsordner von Conclave Personal, nach derselben Regel wie
``conclave.runtime.paths`` (ein Test in Personal haelt beide gleich):

- Windows: ``%APPDATA%\\Conclave`` (ohne APPDATA ``<USERPROFILE>\\AppData\\Roaming\\Conclave``)
- sonst: ``$XDG_CONFIG_HOME/conclave`` (ohne die Variable ``~/.config/conclave``)

Abweichende Orte gibt der Aufrufer ueber ``CONCLAVE_CONFIG_FILE``, ``CONCLAVE_REVIEWER_DATA_DIR`` und
``CONCLAVE_REVIEWER_TOKEN_FILE`` vor oder in ``[reviewer]`` (``reviewer_token_file``).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def conclave_config_dir(env=None, platform: str | None = None, home: Path | None = None) -> Path:
    env = os.environ if env is None else env
    windows = (platform or sys.platform).lower().startswith("win")
    if home is None:
        home = Path(env["USERPROFILE"]) if windows and env.get("USERPROFILE") else Path.home()
    if windows:
        return Path(env.get("APPDATA") or home / "AppData" / "Roaming") / "Conclave"
    return Path(env.get("XDG_CONFIG_HOME") or home / ".config") / "conclave"
