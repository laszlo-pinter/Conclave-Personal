"""Asset-Lokalisierung fuer Source-Checkout und installierte Distributionen."""

from __future__ import annotations

import os
import sys
import sysconfig
from pathlib import Path


def _looks_like_asset_root(path: Path) -> bool:
    return (path / "conclave-ui.html").is_file() and (path / "static").is_dir()


def get_asset_root() -> Path:
    """Findet UI-Assets unabhaengig davon, ob Conclave aus Source oder Wheel laeuft."""
    env_root = os.environ.get("CONCLAVE_ASSET_DIR", "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()

    source_root = Path(__file__).resolve().parents[3]
    data_root = Path(sysconfig.get_path("data")) / "share" / "conclave"
    prefix_root = Path(sys.prefix) / "share" / "conclave"

    for candidate in (source_root, data_root, prefix_root):
        if _looks_like_asset_root(candidate):
            return candidate

    return source_root
