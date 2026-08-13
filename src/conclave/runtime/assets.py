"""Asset-Lokalisierung fuer Source-Checkout und installierte Distributionen."""

from __future__ import annotations

import atexit
import os
from contextlib import ExitStack
from importlib import resources
from pathlib import Path


_RESOURCE_STACK = ExitStack()
atexit.register(_RESOURCE_STACK.close)


def _looks_like_asset_root(path: Path) -> bool:
    return (path / "conclave-ui.html").is_file() and (path / "static").is_dir()


def _package_asset_root() -> Path | None:
    traversable = resources.files("conclave").joinpath("assets")
    try:
        root = _RESOURCE_STACK.enter_context(resources.as_file(traversable))
    except (FileNotFoundError, ModuleNotFoundError):
        return None
    if _looks_like_asset_root(root):
        return root
    return None


def get_asset_root() -> Path:
    """Findet UI-Assets unabhaengig davon, ob Conclave aus Source oder Wheel laeuft."""
    env_root = os.environ.get("CONCLAVE_ASSET_DIR", "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()

    package_root = _package_asset_root()
    if package_root is not None:
        return package_root

    source_root = Path(__file__).resolve().parents[3]
    if _looks_like_asset_root(source_root):
        return source_root
    return source_root
