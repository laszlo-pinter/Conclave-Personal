"""Gemeinsame Sicherheitsregeln fuer den lokalen Workspace."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_AGENT_READ_LIMIT_BYTES = 512 * 1024
DEFAULT_UI_READ_LIMIT_BYTES = 2 * 1024 * 1024
DEFAULT_WRITE_LIMIT_BYTES = 512 * 1024


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def agent_read_limit_bytes() -> int:
    return _int_env("CONCLAVE_WORKSPACE_AGENT_READ_LIMIT_BYTES", DEFAULT_AGENT_READ_LIMIT_BYTES)


def ui_read_limit_bytes() -> int:
    return _int_env("CONCLAVE_WORKSPACE_UI_READ_LIMIT_BYTES", DEFAULT_UI_READ_LIMIT_BYTES)


def write_limit_bytes() -> int:
    return _int_env("CONCLAVE_WORKSPACE_WRITE_LIMIT_BYTES", DEFAULT_WRITE_LIMIT_BYTES)


def workspace_root() -> Path:
    return Path(os.environ.get("CONCLAVE_WORKSPACE", "/workspace")).resolve()


@dataclass(frozen=True)
class WorkspacePath:
    root: Path
    path: Path

    @property
    def relative(self) -> str:
        return self.path.relative_to(self.root).as_posix()


def resolve_workspace_path(relative_path: str, root: Path | None = None) -> WorkspacePath | None:
    """Loest einen Workspace-Pfad auf, falls er innerhalb des Workspace bleibt."""
    root = (root or workspace_root()).resolve()
    if not relative_path or Path(relative_path).is_absolute():
        return None
    path = (root / relative_path).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return WorkspacePath(root=root, path=path)


def resolve_output_path(relative_path: str, root: Path | None = None) -> WorkspacePath | None:
    """Loest einen Agent-Output-Pfad unterhalb von workspace/output auf."""
    root = (root or workspace_root()).resolve()
    output_root = (root / "output").resolve()
    if not relative_path or Path(relative_path).is_absolute():
        return None
    path = (output_root / relative_path).resolve()
    try:
        path.relative_to(output_root)
        path.relative_to(root)
    except ValueError:
        return None
    return WorkspacePath(root=root, path=path)


def is_hidden_workspace_path(path: Path, root: Path | None = None) -> bool:
    root = (root or workspace_root()).resolve()
    try:
        rel = path.resolve().relative_to(root)
    except ValueError:
        return True
    return any(part.startswith(".") and part not in (".", "..") for part in rel.parts)


def is_agent_visible(path: Path, root: Path | None = None) -> bool:
    """Agenten sehen keine versteckten Pfadkomponenten."""
    return not is_hidden_workspace_path(path, root=root)


def assert_size_allowed(path: Path, limit: int) -> bool:
    return path.stat().st_size <= limit


def text_size(content: str) -> int:
    return len(content.encode("utf-8"))
