"""R13 (conclave#48): Secrets und Dateirechte.

- secret.key und Tokens entstehen exklusiv (ein Wert auch bei gleichzeitigem Start)
  und nur fuer den Benutzer lesbar; vorhandene Dateien werden nachgehaertet.
- Unter Windows zeigt icacls danach nur den Benutzer (Datei und Verzeichnis).
- Linux: Verzeichnisse 0o700, DB, Logs und Backups 0o600.
"""

import logging
import os
import stat
import subprocess
import threading

import pytest
from cryptography.fernet import Fernet

from conclave.infrastructure.crypto import CryptoService
from conclave.runtime import file_security
from conclave.runtime.api_token import load_or_create_token

windows = pytest.mark.skipif(os.name != "nt", reason="Windows-ACL")
posix = pytest.mark.skipif(os.name == "nt", reason="POSIX-Rechte")


def _acl_lines(path):
    """ACE-Zeilen aus icacls (ohne Kopf- und Summenzeile)."""
    out = subprocess.run(["icacls", str(path)], capture_output=True, text=True, errors="replace").stdout
    return [line for line in out.splitlines() if ":(" in line]


def _grant_users_read(path):
    # Fremdes, ausdrueckliches Recht wie im Befund (Gruppe "Benutzer" per SID)
    subprocess.run(["icacls", str(path), "/grant", "*S-1-5-32-545:(R)"], capture_output=True, check=True)


# ── Windows-ACL ────────────────────────────────────────────────────────────

@windows
def test_restricted_file_shows_only_the_user(tmp_path):
    path = tmp_path / "secret.key"
    path.write_bytes(b"x")
    _grant_users_read(path)
    assert file_security.foreign_access(path)
    file_security.restrict(path)
    lines = _acl_lines(path)
    assert len(lines) == 1 and os.environ["USERNAME"].lower() in lines[0].lower()
    assert file_security.foreign_access(path) == []


@windows
def test_restricted_directory_shows_only_the_user_and_children_follow(tmp_path):
    folder = tmp_path / "config"
    folder.mkdir()
    _grant_users_read(folder)
    file_security.restrict(folder, directory=True)
    assert len(_acl_lines(folder)) == 1
    child = folder / "neu.txt"
    child.write_text("x")
    assert file_security.foreign_access(child) == []


# ── Exklusives Anlegen ─────────────────────────────────────────────────────

def test_concurrent_starts_create_a_single_key(tmp_path):
    path = tmp_path / "secret.key"
    services, barrier = [], threading.Barrier(8)

    def start():
        barrier.wait()
        services.append(CryptoService.load_or_generate(path))

    threads = [threading.Thread(target=start) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    token = services[0].encrypt("hallo")
    assert all(s.decrypt(token) == "hallo" for s in services)
    assert path.read_bytes().strip() and not list(tmp_path.glob(".*tmp"))
    assert file_security.foreign_access(path) == []


def test_concurrent_starts_create_a_single_token(tmp_path):
    path = tmp_path / "api.token"
    tokens, barrier = [], threading.Barrier(8)

    def start():
        barrier.wait()
        tokens.append(load_or_create_token(path))

    threads = [threading.Thread(target=start) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(tokens)) == 1 and path.read_text().strip() == tokens[0]
    assert file_security.foreign_access(path) == []


@pytest.mark.parametrize("kind", ["key", "token"])
def test_existing_files_are_hardened_with_a_warning(tmp_path, caplog, kind):
    path = tmp_path / ("secret.key" if kind == "key" else "api.token")
    path.write_bytes(Fernet.generate_key() if kind == "key" else b"cvh_vorhanden\n")
    if os.name == "nt":
        _grant_users_read(path)
    else:
        path.chmod(0o644)
    caplog.set_level(logging.WARNING)
    if kind == "key":
        CryptoService.load_or_generate(path)
    else:
        assert load_or_create_token(path) == "cvh_vorhanden"
    assert file_security.foreign_access(path) == []
    assert any("Rechte" in r.getMessage() and str(path) in r.getMessage() for r in caplog.records)


# ── Verzeichnisse beim Start ───────────────────────────────────────────────

def _paths(tmp_path, key_in_config=True):
    from conclave.runtime.paths import RuntimePaths
    config = tmp_path / "config"
    return RuntimePaths(config_dir=config, data_dir=tmp_path / "data", log_dir=tmp_path / "data" / "logs",
                        workspace_dir=tmp_path / "workspace", db_path=tmp_path / "data" / "conclave.db",
                        secret_key_path=(config if key_in_config else tmp_path / "anderswo") / "secret.key")


@windows
def test_startup_protects_the_config_directory(tmp_path):
    paths = _paths(tmp_path)
    paths.config_dir.mkdir()
    _grant_users_read(paths.config_dir)
    file_security.secure_runtime_dirs(paths)
    assert len(_acl_lines(paths.config_dir)) == 1


@windows
def test_startup_leaves_foreign_directories_alone(tmp_path):
    """Liegt der Schluessel nicht im Konfigurationsverzeichnis, wird dieses nicht angefasst."""
    paths = _paths(tmp_path, key_in_config=False)
    paths.config_dir.mkdir()
    _grant_users_read(paths.config_dir)
    file_security.secure_runtime_dirs(paths)
    assert len(_acl_lines(paths.config_dir)) > 1


@posix
def test_posix_directories_and_files_are_private(tmp_path):
    paths = _paths(tmp_path)
    for d in (paths.config_dir, paths.data_dir, paths.log_dir):
        d.mkdir(parents=True, exist_ok=True)
        d.chmod(0o755)
    file_security.secure_runtime_dirs(paths)
    for d in (paths.config_dir, paths.data_dir, paths.log_dir):
        assert stat.S_IMODE(d.stat().st_mode) == 0o700
    db = paths.db_path
    db.write_bytes(b"")
    db.chmod(0o644)
    file_security.restrict(db)
    assert stat.S_IMODE(db.stat().st_mode) == 0o600


@posix
def test_backup_archive_is_private(tmp_path):
    from conclave.runtime.backup import create_backup_archive
    (tmp_path / "ws").mkdir()
    archive = create_backup_archive(db_path=None, workspace_root=tmp_path / "ws", backup_dir=tmp_path / "b")
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600


@posix
def test_sqlite_database_is_private(tmp_path):
    from conclave.cli.bootstrap import build_service
    from conclave.cli.config import ConclaveConfig
    build_service(config=ConclaveConfig(db_path=tmp_path / "c.db"))
    assert stat.S_IMODE((tmp_path / "c.db").stat().st_mode) == 0o600


@posix
def test_log_file_is_private(tmp_path):
    from conclave.infrastructure.log import configure_logging
    path = tmp_path / "logs" / "conclave.log"
    logger = configure_logging("INFO", log_file=path)
    try:
        logger.info("x")
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    finally:
        for handler in list(logger.handlers):
            if getattr(handler, "baseFilename", None):
                logger.removeHandler(handler)
                handler.close()
