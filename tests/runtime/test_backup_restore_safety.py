"""R7 (conclave#42): Backup und Restore atomar, Herkunft pruefen.

- Restore prueft und entpackt alles vorab; ein Fehler hinterlaesst DB und Workspace unveraendert.
- Sicherheits-Backups ueberschreiben sich nicht.
- Backups enthalten keine verlinkten Inhalte (Symlinks, Junctions).
- Backups einer anderen Instanz (oder ohne Herkunftsnachweis) brauchen eine Bestaetigung.
"""

import os
import sqlite3
import sys
import zipfile
from datetime import datetime, timezone

import pytest

from conclave.runtime import backup as backup_mod
from conclave.runtime.backup import (
    ForeignBackupError, WorkspaceBusyError, create_backup_archive, restore_backup_archive,
)

SECRET = b"secret-a"
OTHER = b"secret-b"


def _make_db(path, marker, *, agents=(), extras=False):
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS marker (value TEXT)")
        conn.execute("DELETE FROM marker")
        conn.execute("INSERT INTO marker VALUES (?)", (marker,))
        if agents:
            conn.execute("CREATE TABLE agents (id TEXT PRIMARY KEY, name TEXT, api_url TEXT)")
            conn.executemany("INSERT INTO agents VALUES (?, ?, ?)", agents)
        if extras:
            conn.execute("CREATE VIEW marker_view AS SELECT value FROM marker")
            conn.execute("CREATE TRIGGER marker_trigger AFTER INSERT ON marker BEGIN DELETE FROM marker; END")
    conn.close()


def _marker(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT value FROM marker").fetchone()[0]
    finally:
        conn.close()


@pytest.fixture
def env(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "notes").mkdir(parents=True)
    (workspace / "notes" / "old.md").write_text("alt", encoding="utf-8")
    db = tmp_path / "conclave.db"
    _make_db(db, "old db")
    backups = tmp_path / "backups"
    return tmp_path, workspace, db, backups


def _own_backup(tmp_path, backups, marker="restored db", files=None, secret=SECRET, **db_kwargs):
    """Backup einer Instanz mit ``secret``: eigene DB und eigener Workspace in einem Nebenordner."""
    src = tmp_path / f"src-{abs(hash((marker, secret)))}"
    (src / "ws").mkdir(parents=True, exist_ok=True)
    for rel, text in (files or {"notes/new.md": "neu"}).items():
        (src / "ws" / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / "ws" / rel).write_text(text, encoding="utf-8")
    _make_db(src / "conclave.db", marker, **db_kwargs)
    return create_backup_archive(db_path=src / "conclave.db", workspace_root=src / "ws", backup_dir=backups,
                                 secret=secret)


def _restore(path, db, workspace, backups, **kwargs):
    kwargs.setdefault("secret", SECRET)
    return restore_backup_archive(backup_path=path, db_path=db, workspace_root=workspace, backup_dir=backups,
                                  **kwargs)


def _state(workspace):
    return sorted((p.relative_to(workspace).as_posix(), p.read_bytes()) for p in workspace.rglob("*") if p.is_file())


def _junction(target, link):
    if sys.platform != "win32":
        os.symlink(target, link, target_is_directory=True)
        return
    import _winapi
    _winapi.CreateJunction(str(target), str(link))


# ── Backup: keine verlinkten Inhalte ────────────────────────────────────────

def test_backup_skips_junction_into_another_directory(env):
    tmp_path, workspace, db, backups = env
    outside = tmp_path / "config"
    outside.mkdir()
    (outside / "secret.key").write_text("geheim", encoding="utf-8")
    _junction(outside, workspace / "link")
    path = create_backup_archive(db_path=db, workspace_root=workspace, backup_dir=backups, secret=SECRET)
    names = zipfile.ZipFile(path).namelist()
    assert "workspace/notes/old.md" in names
    assert not any("secret.key" in n or n.startswith("workspace/link") for n in names)


def test_backup_skips_file_symlink(env):
    tmp_path, workspace, db, backups = env
    (tmp_path / "token.txt").write_text("geheim", encoding="utf-8")
    try:
        (workspace / "token-link.txt").symlink_to(tmp_path / "token.txt")
    except OSError:
        pytest.skip("Symlinks nicht verfuegbar")
    path = create_backup_archive(db_path=db, workspace_root=workspace, backup_dir=backups, secret=SECRET)
    assert "workspace/token-link.txt" not in zipfile.ZipFile(path).namelist()


def test_backup_names_do_not_collide_within_the_same_second(env, monkeypatch):
    _, workspace, db, backups = env

    class FixedNow(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 30, 12, 0, 0, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(backup_mod, "datetime", FixedNow)
    first = create_backup_archive(db_path=db, workspace_root=workspace, backup_dir=backups, secret=SECRET)
    second = create_backup_archive(db_path=db, workspace_root=workspace, backup_dir=backups, secret=SECRET)
    assert first != second and first.is_file() and second.is_file()


def test_two_restores_in_the_same_second_keep_two_safety_backups(env, monkeypatch):
    tmp_path, workspace, db, backups = env
    path = _own_backup(tmp_path, backups)

    class FixedNow(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 30, 12, 0, 0, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(backup_mod, "datetime", FixedNow)
    first = _restore(path, db, workspace, backups).pre_restore_backup_path
    second = _restore(path, db, workspace, backups).pre_restore_backup_path
    assert first != second and first.is_file() and second.is_file()
    with zipfile.ZipFile(first) as zf:                       # das erste haelt den Zustand vor allen Restores
        assert zf.read("workspace/notes/old.md") == b"alt"


# ── Restore: alles oder nichts ──────────────────────────────────────────────

def test_restore_through_a_junction_in_the_workspace_changes_nothing(env):
    tmp_path, workspace, db, backups = env
    outside = tmp_path / "outside"
    outside.mkdir()
    _junction(outside, workspace / "link")
    path = _own_backup(tmp_path, backups, files={"link/planted.txt": "x", "notes/new.md": "neu"})
    before = _state(workspace)
    with pytest.raises(ValueError):
        _restore(path, db, workspace, backups, replace_workspace=False)
    assert _marker(db) == "old db"
    assert not (outside / "planted.txt").exists()
    assert _state(workspace) == before


def _corrupt_member(path, name):
    """Inhalt eines unkomprimierten Eintrags veraendern, ohne CRC und Groesse anzupassen."""
    with zipfile.ZipFile(path) as zf:
        info = zf.getinfo(name)
        payload = zf.read(name)
    data = bytearray(path.read_bytes())
    start = data.index(payload, info.header_offset)
    data[start] ^= 0xFF
    path.write_bytes(bytes(data))


def test_restore_with_corrupt_member_changes_nothing(env):
    tmp_path, workspace, db, backups = env
    path = backups / "corrupt.zip"
    backups.mkdir()
    _make_db(tmp_path / "x.db", "restored db")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.write(tmp_path / "x.db", "conclave.db")
        zf.writestr("workspace/a.txt", "inhalt der datei")
    _corrupt_member(path, "workspace/a.txt")
    before = _state(workspace)
    with pytest.raises(ValueError):
        _restore(path, db, workspace, backups, replace_workspace=True, allow_foreign=True)
    assert _marker(db) == "old db"
    assert _state(workspace) == before


def test_restore_with_wrong_size_changes_nothing(env):
    tmp_path, workspace, db, backups = env
    path = backups / "size.zip"
    backups.mkdir()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("workspace/a.txt", "kurz")
    data = bytearray(path.read_bytes())
    with zipfile.ZipFile(path) as zf:
        info = zf.getinfo("workspace/a.txt")
    central = data.rindex(b"PK\x01\x02")                       # Groesse im zentralen Verzeichnis verfaelschen
    data[central + 24:central + 28] = (info.file_size + 100).to_bytes(4, "little")
    path.write_bytes(bytes(data))
    before = _state(workspace)
    with pytest.raises(ValueError):
        _restore(path, db, workspace, backups, replace_workspace=True, allow_foreign=True)
    assert _marker(db) == "old db"
    assert _state(workspace) == before


def test_db_failure_after_workspace_swap_restores_the_old_workspace(env, monkeypatch):
    tmp_path, workspace, db, backups = env
    path = _own_backup(tmp_path, backups)
    before = _state(workspace)

    def boom(*args, **kwargs):
        raise OSError("db gesperrt")

    monkeypatch.setattr(backup_mod, "_restore_db", boom)
    with pytest.raises(OSError):
        _restore(path, db, workspace, backups, replace_workspace=True)
    assert _state(workspace) == before
    assert _marker(db) == "old db"


def test_successful_restore_replaces_workspace_and_db(env):
    tmp_path, workspace, db, backups = env
    path = _own_backup(tmp_path, backups)
    result = _restore(path, db, workspace, backups, replace_workspace=True)
    assert result.db_restored and result.workspace_replaced and result.origin == "own"
    assert _marker(db) == "restored db"
    assert _state(workspace) == [("notes/new.md", b"neu")]
    leftovers = [p.name for p in workspace.parent.iterdir() if p.name.startswith(".")]
    assert leftovers == []                                     # kein Staging bleibt liegen


def test_restore_merges_into_the_workspace_when_asked(env):
    tmp_path, workspace, db, backups = env
    path = _own_backup(tmp_path, backups)
    _restore(path, db, workspace, backups, replace_workspace=False)
    assert _state(workspace) == [("notes/new.md", b"neu"), ("notes/old.md", b"alt")]


def test_restore_drops_triggers_and_views(env):
    tmp_path, workspace, db, backups = env
    path = _own_backup(tmp_path, backups, extras=True)
    _restore(path, db, workspace, backups)
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT name FROM sqlite_master WHERE type IN ('trigger', 'view')").fetchall() == []
    finally:
        conn.close()


# ── Herkunft ────────────────────────────────────────────────────────────────

def test_backup_from_another_instance_needs_confirmation(env):
    tmp_path, workspace, db, backups = env
    path = _own_backup(tmp_path, backups, secret=OTHER,
                       agents=[("gpt", "GPT", "https://gateway.example/v1"), ("claude", "Claude", "")])
    before = _state(workspace)
    with pytest.raises(ForeignBackupError) as info:
        _restore(path, db, workspace, backups)
    assert [(a["id"], a["api_url"]) for a in info.value.agents] == [
        ("claude", ""), ("gpt", "https://gateway.example/v1")]
    assert _marker(db) == "old db" and _state(workspace) == before
    assert not list(backups.glob("conclave-pre-restore-*"))  # noch nichts angefasst

    result = _restore(path, db, workspace, backups, allow_foreign=True)
    assert result.origin == "foreign"
    assert _marker(db) == "restored db"


def test_backup_without_manifest_needs_confirmation(env):
    tmp_path, workspace, db, backups = env
    backups.mkdir()
    _make_db(tmp_path / "x.db", "restored db")
    path = backups / "handmade.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.write(tmp_path / "x.db", "conclave.db")
    with pytest.raises(ForeignBackupError):
        _restore(path, db, workspace, backups)
    assert _marker(db) == "old db"


def test_changed_content_of_own_backup_needs_confirmation(env):
    tmp_path, workspace, db, backups = env
    path = _own_backup(tmp_path, backups)
    with zipfile.ZipFile(path) as zf:
        entries = {n: zf.read(n) for n in zf.namelist()}
    entries["workspace/notes/new.md"] = b"untergeschoben"
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    with pytest.raises(ForeignBackupError):
        _restore(path, db, workspace, backups)
    assert _marker(db) == "old db"


def test_own_backup_restores_without_confirmation(env):
    tmp_path, workspace, db, backups = env
    path = create_backup_archive(db_path=db, workspace_root=workspace, backup_dir=backups, secret=SECRET)
    _make_db(db, "changed")
    assert _restore(path, db, workspace, backups).origin == "own"
    assert _marker(db) == "old db"


def test_backup_without_secret_counts_as_foreign(env):
    tmp_path, workspace, db, backups = env
    path = create_backup_archive(db_path=db, workspace_root=workspace, backup_dir=backups, secret=None)
    with pytest.raises(ForeignBackupError):
        _restore(path, db, workspace, backups)


# ── Nacharbeit aus dem Review ───────────────────────────────────────────────

def test_replacing_a_workspace_with_a_junction_leaves_the_junction_target_intact(env):
    tmp_path, workspace, db, backups = env
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "wichtig.txt").write_text("bleibt", encoding="utf-8")
    _junction(outside, workspace / "link")
    path = _own_backup(tmp_path, backups)
    _restore(path, db, workspace, backups, replace_workspace=True)
    assert (outside / "wichtig.txt").read_text(encoding="utf-8") == "bleibt"
    assert _state(workspace) == [("notes/new.md", b"neu")]


def test_busy_workspace_reports_clearly_and_changes_nothing(env, monkeypatch):
    tmp_path, workspace, db, backups = env
    path = _own_backup(tmp_path, backups)
    before = _state(workspace)
    real = os.replace

    def busy(src, dst):
        if os.path.abspath(src) == str(workspace):
            raise PermissionError(32, "Datei wird verwendet")
        return real(src, dst)

    monkeypatch.setattr(backup_mod.os, "replace", busy)
    with pytest.raises(WorkspaceBusyError, match="in Benutzung"):
        _restore(path, db, workspace, backups, replace_workspace=True)
    monkeypatch.undo()
    assert _state(workspace) == before and _marker(db) == "old db"


def test_file_used_as_folder_is_an_invalid_backup(env):
    tmp_path, workspace, db, backups = env
    backups.mkdir()
    path = backups / "clash.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("workspace/a", "datei")
        zf.writestr("workspace/a/b", "darunter")
    with pytest.raises(ValueError, match="folder"):
        _restore(path, db, workspace, backups, allow_foreign=True)


def test_name_collision_never_deletes_an_existing_backup(env, monkeypatch):
    _, workspace, db, backups = env
    backups.mkdir()
    existing = backups / "fest.zip"
    existing.write_bytes(b"vorhandenes backup")
    monkeypatch.setattr(backup_mod, "_new_backup_path", lambda directory, prefix: existing)
    with pytest.raises(FileExistsError):
        create_backup_archive(db_path=db, workspace_root=workspace, backup_dir=backups, secret=SECRET)
    assert existing.read_bytes() == b"vorhandenes backup"
