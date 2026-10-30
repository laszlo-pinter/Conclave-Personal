"""Backup and restore helpers for local Conclave runtime data.

Ein Restore prueft und entpackt erst alles in ein Staging-Verzeichnis, tauscht dann
den Workspace und spielt die DB zuletzt ein. Schlaegt ein Schritt fehl, bleibt der
alte Zustand erhalten (R7). Jedes Backup traegt ein Manifest mit Instanz-ID und
HMAC ueber den Inhalt; ohne gueltige eigene Herkunft verlangt der Restore eine
Bestaetigung.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import shutil
import sqlite3
import stat
import tempfile
import zipfile
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from conclave.runtime.env import env_secret


DEFAULT_RESTORE_MAX_BYTES = 512 * 1024 * 1024
MANIFEST_NAME = "manifest.json"
MANIFEST_MAX_BYTES = 8 * 1024 * 1024
MANIFEST_FORMAT = 1
_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class RestoreResult:
    pre_restore_backup_path: Path
    db_restored: bool
    workspace_files_restored: int
    workspace_replaced: bool
    origin: str = "own"                      # "own" oder "foreign" (bestaetigt)


@dataclass
class ForeignBackupError(Exception):
    """Das Backup stammt nicht nachweislich von dieser Instanz; Restore nur mit Bestaetigung."""

    reason: str
    agents: list[dict] = field(default_factory=list)

    def __str__(self) -> str:
        return f"Herkunft des Backups nicht belegt ({self.reason}). Restore nur mit Bestaetigung."


class WorkspaceBusyError(OSError):
    """Der Workspace laesst sich nicht tauschen, weil ein Prozess darin Dateien offen hat."""


def load_backup_secret() -> bytes | None:
    """Schluessel fuer das Backup-Manifest: derselbe wie fuer die Verschluesselung (secret.key).

    Legt keinen Schluessel an; ohne Schluessel sind Backups nicht signiert.
    """
    env_key = env_secret("CONCLAVE_SECRET_KEY")
    if env_key:
        return env_key.encode()
    from conclave.runtime.paths import get_runtime_paths
    path = get_runtime_paths().secret_key_path
    try:
        return path.read_bytes() if path.is_file() else None
    except OSError:
        return None


def instance_id(secret: bytes) -> str:
    """Oeffentliche Kennung der Instanz, abgeleitet aus dem Schluessel (nicht umkehrbar)."""
    return hmac.new(secret, b"conclave-instance-id-v1", hashlib.sha256).hexdigest()[:16]


def _manifest_mac(secret: bytes, body: dict) -> str:
    key = hmac.new(secret, b"conclave-backup-manifest-v1", hashlib.sha256).digest()
    payload = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


# ── Backup ──────────────────────────────────────────────────────────────────

def create_backup_archive(
    *,
    db_path: Path | None,
    workspace_root: Path,
    backup_dir: Path,
    prefix: str = "conclave-backup",
    secret: bytes | None = None,
) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    workspace_root = workspace_root.resolve()
    backup_path = _new_backup_path(backup_dir, prefix)
    files: dict[str, dict] = {}

    # Modus "x": ein vorhandenes Backup wird nie ueberschrieben; aufgeraeumt wird nur das eigene
    archive = zipfile.ZipFile(backup_path, "x", compression=zipfile.ZIP_DEFLATED)
    try:
        with archive as zf:
            if db_path and db_path.is_file():
                with tempfile.TemporaryDirectory(dir=str(backup_dir), prefix=".snapshot-") as tmp_dir:
                    snapshot = Path(tmp_dir) / "conclave.db"
                    _snapshot_db(db_path, snapshot)
                    files["conclave.db"] = _add_file(zf, snapshot, "conclave.db")
            if workspace_root.is_dir():
                for path in _workspace_files(workspace_root, skip=backup_path.resolve()):
                    arcname = PurePosixPath("workspace", *path.relative_to(workspace_root).parts).as_posix()
                    files[arcname] = _add_file(zf, path, arcname)
            body = {
                "format": MANIFEST_FORMAT,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "instance_id": instance_id(secret) if secret else None,
                "files": files,
            }
            manifest = dict(body, hmac=_manifest_mac(secret, body) if secret else None)
            zf.writestr(MANIFEST_NAME, json.dumps(manifest, sort_keys=True, indent=1))
    except BaseException:
        backup_path.unlink(missing_ok=True)
        raise

    return backup_path


def _new_backup_path(backup_dir: Path, prefix: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return backup_dir / f"{prefix}-{stamp}-{secrets.token_hex(3)}.zip"


def _snapshot_db(db_path: Path, target: Path) -> None:
    """Konsistenter Stand der laufenden DB ueber die SQLite-Backup-API; sonst Dateikopie."""
    try:
        source = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True, timeout=30)
        try:
            dest = sqlite3.connect(str(target))
            try:
                source.backup(dest)
            finally:
                dest.close()
        finally:
            source.close()
    except sqlite3.DatabaseError:
        target.unlink(missing_ok=True)
        shutil.copyfile(db_path, target)


def _add_file(zf: zipfile.ZipFile, path: Path, arcname: str) -> dict:
    info = zipfile.ZipInfo.from_file(path, arcname)
    info.compress_type = zipfile.ZIP_DEFLATED
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as src, zf.open(info, "w", force_zip64=info.file_size > zipfile.ZIP64_LIMIT) as dst:
        while chunk := src.read(_CHUNK):
            digest.update(chunk)
            size += len(chunk)
            dst.write(chunk)
    return {"size": size, "sha256": digest.hexdigest()}


def _is_link(path: Path) -> bool:
    """Symlink oder Junction (bzw. Mount-Point unter Windows)."""
    if path.is_symlink():
        return True
    isjunction = getattr(os.path, "isjunction", None)
    if isjunction is not None:
        return isjunction(path)
    try:
        tag = getattr(os.lstat(path), "st_reparse_tag", 0)
    except OSError:
        return True                                # nicht pruefbar: wie ein Link behandeln
    return tag == getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", -1)


def _workspace_files(root: Path, skip: Path):
    """Regulaere Dateien unterhalb von ``root``; Links und alles ausserhalb der Wurzel bleiben draussen."""
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda e: e.name)
        except OSError:
            continue
        for entry in entries:
            path = Path(entry.path)
            if _is_link(path):
                continue
            try:
                path.resolve().relative_to(root)
            except ValueError:
                continue
            if entry.is_dir(follow_symlinks=False):
                pending.append(path)
            elif entry.is_file(follow_symlinks=False) and path.resolve() != skip:
                yield path


# ── Restore ─────────────────────────────────────────────────────────────────

def restore_backup_archive(
    *,
    backup_path: Path,
    db_path: Path | None,
    workspace_root: Path,
    backup_dir: Path,
    replace_workspace: bool = True,
    secret: bytes | None = None,
    allow_foreign: bool = False,
) -> RestoreResult:
    backup_path = backup_path.expanduser().resolve()
    workspace_root = workspace_root.expanduser().resolve()
    backup_dir = backup_dir.expanduser().resolve()
    if workspace_root == workspace_root.parent:
        raise ValueError("Refusing to restore into the filesystem root.")
    workspace_root.parent.mkdir(parents=True, exist_ok=True)

    staging = Path(tempfile.mkdtemp(dir=str(workspace_root.parent), prefix=f".{workspace_root.name}-restore-"))
    try:
        # 1. Alles pruefen und ins Staging entpacken, bevor irgendetwas geaendert wird
        try:
            with zipfile.ZipFile(backup_path, "r") as zf:
                members = zf.infolist()
                _validate_members(members)
                if zf.testzip() is not None:
                    raise ValueError("Backup archive is corrupt (checksum mismatch).")
                staged_db, staged_files, digests = _stage(zf, members, staging)
                manifest = _read_manifest(zf, members)
        except zipfile.BadZipFile as exc:
            raise ValueError("Backup archive is not a valid ZIP file.") from exc
        except (EOFError, zlib.error) as exc:
            raise ValueError("Backup archive is corrupt.") from exc

        reason = _origin_problem(manifest, digests, secret)
        if staged_db is not None:
            _check_and_clean_db(staged_db)
        if reason is not None and not allow_foreign:
            raise ForeignBackupError(reason, _agents_in(staged_db) if staged_db is not None else [])

        staged_workspace = staging / "workspace"
        if staged_files and not replace_workspace:
            _preflight_merge(workspace_root, staged_files)

        # 2. Sicherheits-Backup des aktuellen Zustands
        pre_restore_backup = create_backup_archive(
            db_path=db_path,
            workspace_root=workspace_root,
            backup_dir=backup_dir,
            prefix="conclave-pre-restore",
            secret=secret,
        )

        # 3. Workspace tauschen, 4. DB zuletzt; bei einem Fehler zurueck
        undo = None
        if staged_files:
            try:
                if replace_workspace:
                    undo = _swap_workspace(staged_workspace, workspace_root, staging / "previous")
                else:
                    undo = _merge_workspace(staged_workspace, workspace_root, staged_files, staging / "previous")
            except PermissionError as exc:
                raise WorkspaceBusyError(
                    "Workspace ist in Benutzung (eine Datei darin ist geoeffnet). "
                    "Programme schliessen und erneut versuchen; es wurde nichts geaendert.") from exc
        db_restored = False
        try:
            if staged_db is not None and db_path is not None:
                _restore_db(staged_db, db_path)
                db_restored = True
        except BaseException:
            if undo is not None:
                undo()
            raise

        return RestoreResult(
            pre_restore_backup_path=pre_restore_backup,
            db_restored=db_restored,
            workspace_files_restored=len(staged_files),
            workspace_replaced=replace_workspace,
            origin="own" if reason is None else "foreign",
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)   # folgt unter Windows keinen Junctions


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
    seen: set[str] = set()
    files: list[str] = []
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
        if parts[0] != "workspace" and parts not in (("conclave.db",), (MANIFEST_NAME,)):
            raise ValueError(f"Backup archive contains an unsupported path: {member.filename}")
        if _is_symlink(member):
            raise ValueError(f"Backup archive contains a symlink: {member.filename}")
        key = path.as_posix().lower()                # Windows: Gross/Klein gilt als derselbe Name
        if not member.is_dir():
            if key in seen:
                raise ValueError(f"Backup archive contains a duplicate path: {member.filename}")
            seen.add(key)
            files.append(key)
            total_size += max(0, member.file_size)
            if total_size > _restore_limit_bytes():
                raise ValueError("Backup archive exceeds the configured restore size limit.")
    for key in files:                                # Datei und Ordner mit demselben Namen
        parent = PurePosixPath(key).parent
        while parent.parts:
            if parent.as_posix() in seen:
                raise ValueError(f"Backup archive uses a file name as a folder: {parent.as_posix()}")
            parent = parent.parent


def _member_path(member: zipfile.ZipInfo) -> PurePosixPath:
    return PurePosixPath(member.filename)


def _is_symlink(member: zipfile.ZipInfo) -> bool:
    mode = (member.external_attr >> 16) & 0o170000
    return mode == stat.S_IFLNK


def _stage(zf: zipfile.ZipFile, members: list[zipfile.ZipInfo], staging: Path):
    """Entpackt DB und Workspace-Dateien ins Staging; liefert Pfade und Pruefsummen."""
    staged_db = None
    staged_files: list[PurePosixPath] = []
    digests: dict[str, dict] = {}
    budget = [_restore_limit_bytes()]
    for member in members:
        parts = _member_path(member).parts
        if member.is_dir() or parts == (MANIFEST_NAME,):
            continue
        if parts == ("conclave.db",):
            staged_db = staging / "conclave.db"
            digests[member.filename] = _extract(zf, member, staged_db, budget)
        elif len(parts) > 1:
            rel = PurePosixPath(*parts[1:])
            digests[member.filename] = _extract(zf, member, staging / "workspace" / rel, budget)
            staged_files.append(rel)
    return staged_db, staged_files, digests


def _extract(zf: zipfile.ZipFile, member: zipfile.ZipInfo, target: Path, budget: list[int]) -> dict:
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    with zf.open(member, "r") as src, open(target, "xb") as dst:
        while chunk := src.read(_CHUNK):
            size += len(chunk)
            budget[0] -= len(chunk)
            if budget[0] < 0:
                raise ValueError("Backup archive exceeds the configured restore size limit.")
            digest.update(chunk)
            dst.write(chunk)
    if size != member.file_size:
        raise ValueError(f"Backup archive member has a wrong size: {member.filename}")
    return {"size": size, "sha256": digest.hexdigest()}


def _read_manifest(zf: zipfile.ZipFile, members: list[zipfile.ZipInfo]) -> dict | None:
    member = next((m for m in members if m.filename == MANIFEST_NAME), None)
    if member is None or member.file_size > MANIFEST_MAX_BYTES:
        return None
    try:
        data = json.loads(zf.read(member).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _origin_problem(manifest: dict | None, digests: dict[str, dict], secret: bytes | None) -> str | None:
    """None, wenn das Backup nachweislich von dieser Instanz stammt und unveraendert ist."""
    if manifest is None:
        return "kein Manifest"
    if not secret:
        return "kein Schluessel zum Pruefen"
    mac = manifest.get("hmac")
    body = {k: v for k, v in manifest.items() if k != "hmac"}
    if not isinstance(mac, str) or not mac:
        return "nicht signiert"
    if manifest.get("instance_id") != instance_id(secret):
        return "andere Instanz"
    if not hmac.compare_digest(mac, _manifest_mac(secret, body)):
        return "Signatur ungueltig"
    if manifest.get("files") != digests:
        return "Inhalt veraendert"
    return None


def _check_and_clean_db(path: Path) -> None:
    """Integritaet pruefen; Trigger und Views verwerfen (das Schema von Conclave hat keine)."""
    conn = sqlite3.connect(str(path))
    try:
        try:
            ok = conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        except sqlite3.DatabaseError as exc:
            raise ValueError("Backup archive contains no valid SQLite database.") from exc
        if not ok:
            raise ValueError("Backup database failed the SQLite integrity check.")
        objects = conn.execute("SELECT type, name FROM sqlite_master WHERE type IN ('trigger', 'view')").fetchall()
        for kind, name in objects:
            quoted = '"' + str(name).replace('"', '""') + '"'
            conn.execute(f"DROP {'TRIGGER' if kind == 'trigger' else 'VIEW'} IF EXISTS {quoted}")
        conn.commit()
    finally:
        conn.close()


def _agents_in(path: Path) -> list[dict]:
    """Agents der Backup-DB fuer die Warnung (ID und Ziel-URL)."""
    conn = sqlite3.connect(str(path))
    try:
        rows = conn.execute("SELECT id, api_url FROM agents ORDER BY id").fetchall()
    except sqlite3.DatabaseError:
        return []
    finally:
        conn.close()
    return [{"id": str(agent_id), "api_url": str(api_url or "")} for agent_id, api_url in rows]


def _preflight_merge(workspace_root: Path, files: list[PurePosixPath]) -> None:
    """Zusammenfuehren: Jedes Ziel muss eine normale Datei (oder frei) in normalen Ordnern sein."""
    for rel in files:
        current = workspace_root
        for part in rel.parts[:-1]:
            current = current / part
            if current.is_symlink() or (current.exists() and (_is_link(current) or not current.is_dir())):
                raise ValueError(f"Backup archive contains an unsafe workspace path: workspace/{rel}")
        target = workspace_root / Path(*rel.parts)
        if target.is_symlink() or (target.exists() and (_is_link(target) or not target.is_file())):
            raise ValueError(f"Backup archive contains an unsafe workspace path: workspace/{rel}")


def _swap_workspace(staged: Path, workspace_root: Path, previous: Path):
    """Ersetzt den Workspace per Rename; liefert die Rueckgaengig-Funktion."""
    had_workspace = workspace_root.exists()
    if had_workspace:
        os.replace(workspace_root, previous)
    try:
        os.replace(staged, workspace_root)
    except BaseException:
        if had_workspace:
            os.replace(previous, workspace_root)
        raise

    def undo():
        os.replace(workspace_root, staged)
        if had_workspace:
            os.replace(previous, workspace_root)

    return undo


def _merge_workspace(staged: Path, workspace_root: Path, files: list[PurePosixPath], previous: Path):
    """Legt Dateien einzeln per Rename in den Workspace; ueberschriebene wandern nach ``previous``."""
    replaced: list[Path] = []
    added: list[Path] = []
    created_dirs: list[Path] = []

    def undo():
        for target in reversed(added):
            target.unlink(missing_ok=True)
        for rel in reversed(replaced):
            os.replace(previous / rel, workspace_root / rel)
        for directory in reversed(created_dirs):
            try:
                directory.rmdir()
            except OSError:
                pass

    try:
        for rel in files:
            rel_path = Path(*rel.parts)
            target = workspace_root / rel_path
            for parent in reversed(target.parents):
                if parent == workspace_root or workspace_root in parent.parents:
                    if not parent.exists():
                        parent.mkdir()
                        created_dirs.append(parent)
            if target.exists():
                (previous / rel_path).parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, previous / rel_path)
                replaced.append(rel_path)
            os.replace(staged / rel_path, target)
            added.append(target)
    except BaseException:
        undo()
        raise
    return undo


def _restore_db(staged_db: Path, db_path: Path) -> None:
    """Spielt die gepruefte Backup-DB ueber die SQLite-Backup-API in die bestehende DB ein.

    Die Datei wird nicht ersetzt: offene Verbindungen des laufenden Servers und
    die WAL-Dateien bleiben gueltig und sehen die wiederhergestellten Daten ab
    ihrer naechsten Transaktion. Die Backup-API schreibt in einer Transaktion.
    """
    db_path = db_path.expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(str(staged_db))
    try:
        target = sqlite3.connect(str(db_path), timeout=30)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
