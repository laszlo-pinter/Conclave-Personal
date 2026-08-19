"""Backup and restore helpers for local Conclave runtime data."""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


DEFAULT_RESTORE_MAX_BYTES = 512 * 1024 * 1024


@dataclass(frozen=True)
class RestoreResult:
    pre_restore_backup_path: Path
    db_restored: bool
    workspace_files_restored: int
    workspace_replaced: bool


def create_backup_archive(
    *,
    db_path: Path | None,
    workspace_root: Path,
    backup_dir: Path,
    prefix: str = "conclave-backup",
) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"{prefix}-{stamp}.zip"
    workspace_root = workspace_root.resolve()

    with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if db_path and db_path.is_file():
            zf.write(db_path, "conclave.db")
        if workspace_root.is_dir():
            for path in workspace_root.rglob("*"):
                if not path.is_file():
                    continue
                if path.resolve() == backup_path.resolve():
                    continue
                zf.write(path, PurePosixPath("workspace", *path.relative_to(workspace_root).parts).as_posix())

    return backup_path


def restore_backup_archive(
    *,
    backup_path: Path,
    db_path: Path | None,
    workspace_root: Path,
    backup_dir: Path,
    replace_workspace: bool = True,
) -> RestoreResult:
    backup_path = backup_path.expanduser().resolve()
    workspace_root = workspace_root.expanduser().resolve()
    backup_dir = backup_dir.expanduser().resolve()

    try:
        with zipfile.ZipFile(backup_path, "r") as zf:
            members = zf.infolist()
            _validate_members(members)

            db_member = next((m for m in members if _member_path(m).parts == ("conclave.db",)), None)
            workspace_members = [
                m for m in members
                if not m.is_dir() and len(_member_path(m).parts) > 1 and _member_path(m).parts[0] == "workspace"
            ]

            pre_restore_backup = create_backup_archive(
                db_path=db_path,
                workspace_root=workspace_root,
                backup_dir=backup_dir,
                prefix="conclave-pre-restore",
            )

            db_restored = False
            if db_member is not None and db_path is not None:
                _restore_db(zf, db_member, db_path)
                db_restored = True

            if workspace_members:
                if replace_workspace:
                    _clear_directory_contents(workspace_root)
                workspace_root.mkdir(parents=True, exist_ok=True)
                for member in workspace_members:
                    _restore_workspace_member(zf, member, workspace_root)

            return RestoreResult(
                pre_restore_backup_path=pre_restore_backup,
                db_restored=db_restored,
                workspace_files_restored=len(workspace_members),
                workspace_replaced=replace_workspace,
            )
    except zipfile.BadZipFile as exc:
        raise ValueError("Backup archive is not a valid ZIP file.") from exc


def _restore_limit_bytes() -> int:
    raw = os.environ.get("CONCLAVE_RESTORE_MAX_BYTES", "").strip()
    if not raw:
        return DEFAULT_RESTORE_MAX_BYTES
    try:
        parsed = int(raw)
    except ValueError:
        return DEFAULT_RESTORE_MAX_BYTES
    return parsed if parsed > 0 else DEFAULT_RESTORE_MAX_BYTES


def _validate_members(members: list[zipfile.ZipInfo]) -> None:
    total_size = 0
    for member in members:
        path = _member_path(member)
        parts = path.parts
        if not parts:
            raise ValueError("Backup archive contains an empty path.")
        if "\\" in member.filename:
            raise ValueError(f"Backup archive contains an invalid path: {member.filename}")
        if any(part in ("", ".", "..") for part in parts):
            raise ValueError(f"Backup archive contains an unsafe path: {member.filename}")
        if any(":" in part for part in parts):
            raise ValueError(f"Backup archive contains an unsafe path: {member.filename}")
        if path.is_absolute():
            raise ValueError(f"Backup archive contains an absolute path: {member.filename}")
        if parts[0] != "workspace" and parts != ("conclave.db",):
            raise ValueError(f"Backup archive contains an unsupported path: {member.filename}")
        if _is_symlink(member):
            raise ValueError(f"Backup archive contains a symlink: {member.filename}")
        if not member.is_dir():
            total_size += max(0, member.file_size)
            if total_size > _restore_limit_bytes():
                raise ValueError("Backup archive exceeds the configured restore size limit.")


def _member_path(member: zipfile.ZipInfo) -> PurePosixPath:
    return PurePosixPath(member.filename)


def _is_symlink(member: zipfile.ZipInfo) -> bool:
    mode = (member.external_attr >> 16) & 0o170000
    return mode == stat.S_IFLNK


def _restore_db(zf: zipfile.ZipFile, member: zipfile.ZipInfo, db_path: Path) -> None:
    db_path = db_path.expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, dir=str(db_path.parent), suffix=".restore") as tmp:
        tmp_path = Path(tmp.name)
        with zf.open(member, "r") as src:
            shutil.copyfileobj(src, tmp)
    os.replace(tmp_path, db_path)


def _restore_workspace_member(zf: zipfile.ZipFile, member: zipfile.ZipInfo, workspace_root: Path) -> None:
    rel = Path(*_member_path(member).parts[1:])
    target = (workspace_root / rel).resolve()
    try:
        target.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError(f"Backup archive contains an unsafe workspace path: {member.filename}") from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    with zf.open(member, "r") as src, open(target, "wb") as dst:
        shutil.copyfileobj(src, dst)


def _clear_directory_contents(root: Path) -> None:
    root = root.expanduser().resolve()
    if root == root.parent:
        raise ValueError("Refusing to clear filesystem root during restore.")
    root.mkdir(parents=True, exist_ok=True)
    for child in root.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
