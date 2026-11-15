"""R15 (conclave#50): Echte Abstuerze waehrend Migration, Workspace-Write und Restore.

Ein Unterprozess bricht an einer festgelegten Stelle mit ``os._exit`` ab: kein
``except``, kein ``finally``, keine Aufraeumarbeit, wie bei einem Stromausfall
oder einem beendeten Prozess. Danach muss der Zustand konsistent sein bzw. beim
naechsten Start wiederhergestellt werden.

Die Zustellung von Consultations ist in tests/application/test_consultation_service.py
abgedeckt (Zustand nach Abbruch zwischen Kommentar und "delivered").
"""

import json
import os
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from conclave.runtime.backup import create_backup_archive, recover_interrupted_restores

ROOT = Path(__file__).resolve().parents[2]
CRASH = 3


def _run_crashing(code: str, **params) -> int:
    """Fuehrt ``code`` in einem eigenen Prozess aus; ``params`` stehen dort als JSON in P."""
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""))
    script = "import json, os, sys\nP = json.loads(sys.argv[1])\n" + textwrap.dedent(code)
    result = subprocess.run([sys.executable, "-c", script, json.dumps(params)], env=env,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == CRASH, result.stderr[-2000:]
    return result.returncode


# ── Migration ────────────────────────────────────────────────────────────────

def test_crash_during_migration_leaves_the_schema_and_data_intact(tmp_path):
    from conclave.infrastructure.migrations import Migration, _get_applied, run_migrations
    from conclave.infrastructure.sqlite.schema import initialize_schema
    db = tmp_path / "c.db"
    conn = sqlite3.connect(db)
    initialize_schema(conn)                                              # Schema samt aller Migrationen
    conn.execute("INSERT INTO conversations (id, status, created_at) VALUES ('vorher', 'open', '2026-01-01')")
    conn.commit()
    conn.close()

    _run_crashing("""
        import sqlite3
        from conclave.infrastructure.migrations import Migration, run_migrations

        class Crashing:
            # Leitet alles an die Verbindung weiter; bricht mitten in der Migration ab
            def __init__(self, conn):
                self._conn = conn
            def execute(self, sql, *args):
                if "crash_hier" in sql:
                    os._exit(3)
                return self._conn.execute(sql, *args)
            def __getattr__(self, name):
                return getattr(self._conn, name)

        conn = sqlite3.connect(P["db"])
        run_migrations(Crashing(conn), is_postgres=False, migrations=[Migration(
            id="950_crash", description="Absturz mittendrin",
            statements=("CREATE TABLE crash_a (x INTEGER)",
                        "UPDATE conversations SET status = 'geaendert'",
                        "SELECT 'crash_hier'"))])
    """, db=str(db))

    conn = sqlite3.connect(db)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "crash_a" not in tables                                   # DDL nicht uebernommen
        assert conn.execute("SELECT status FROM conversations WHERE id='vorher'").fetchone() == ("open",)
        assert "950_crash" not in _get_applied(conn, is_postgres=False)
        fixed = [Migration(id="950_crash", description="repariert", statements=("CREATE TABLE crash_a (x INTEGER)",))]
        assert run_migrations(conn, is_postgres=False, migrations=fixed) == ["950_crash"]
    finally:
        conn.close()


# ── Workspace-Write ──────────────────────────────────────────────────────────

def test_crash_during_workspace_write_keeps_the_old_file(tmp_path):
    target = tmp_path / "ws" / "notiz.md"
    target.parent.mkdir()
    target.write_text("alt", encoding="utf-8")

    _run_crashing("""
        from pathlib import Path
        from conclave.application import workspace_security
        def crash(*args, **kwargs):
            os._exit(3)                       # Datei ist geschrieben, aber noch nicht umbenannt
        workspace_security.os.replace = crash
        workspace_security.write_text_atomic(Path(P["target"]), "neu und halb")
    """, target=str(target))

    assert target.read_text(encoding="utf-8") == "alt"
    leftovers = [p.name for p in target.parent.iterdir() if p != target]
    assert all(name.startswith(".") for name in leftovers), leftovers    # versteckt, nie als Workspace-Datei


# ── Restore ──────────────────────────────────────────────────────────────────

def _make_db(path, marker):
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS marker (value TEXT)")
        conn.execute("DELETE FROM marker")
        conn.execute("INSERT INTO marker VALUES (?)", (marker,))
    conn.close()


def _marker(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT value FROM marker").fetchone()[0]
    finally:
        conn.close()


def _state(workspace):
    return sorted((p.relative_to(workspace).as_posix(), p.read_text(encoding="utf-8"))
                  for p in workspace.rglob("*") if p.is_file())


@pytest.fixture
def restore_env(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "notes").mkdir(parents=True)
    (workspace / "notes" / "alt.md").write_text("alt", encoding="utf-8")
    (workspace / "notes" / "beide.md").write_text("alt", encoding="utf-8")
    db = tmp_path / "conclave.db"
    _make_db(db, "alte db")
    src = tmp_path / "quelle"
    (src / "ws" / "notes").mkdir(parents=True)
    (src / "ws" / "notes" / "neu.md").write_text("neu", encoding="utf-8")
    (src / "ws" / "notes" / "beide.md").write_text("neu", encoding="utf-8")
    _make_db(src / "conclave.db", "neue db")
    archive = create_backup_archive(db_path=src / "conclave.db", workspace_root=src / "ws",
                                    backup_dir=tmp_path / "backups", secret=b"geheim")
    return tmp_path, workspace, db, archive


RESTORE_CRASH = """
    from pathlib import Path
    from conclave.runtime import backup
    real_replace, calls = backup.os.replace, [0]
    def counting(src, dst):
        calls[0] += 1
        if calls[0] == P["crash_at"] and P["before"]:
            os._exit(3)
        real_replace(src, dst)
        if calls[0] == P["crash_at"]:
            os._exit(3)
    backup.os.replace = counting
    def crash_db(*args, **kwargs):
        os._exit(3)
    if P["crash_in_db"]:
        backup._restore_db = crash_db
    backup.restore_backup_archive(backup_path=Path(P["archive"]), db_path=Path(P["db"]),
                                  workspace_root=Path(P["workspace"]), backup_dir=Path(P["backups"]),
                                  replace_workspace=P["replace"], secret=b"geheim")
    os._exit(0)
"""


@pytest.mark.parametrize("replace, crash_at, before, crash_in_db", [
    (True, 1, False, False),    # alter Workspace weggeschoben, neuer noch nicht da: Ordner fehlt
    (True, 2, False, False),    # neuer Workspace liegt schon da, DB noch alt
    (True, 99, False, True),    # Absturz beim Einspielen der DB
    (False, 1, False, False),   # Zusammenfuehren: ueberschriebene Datei weggeschoben
    (False, 2, False, False),   # Zusammenfuehren: erste neue Datei eingespielt
    (False, 99, False, True),   # Zusammenfuehren fertig, Absturz bei der DB
])
def test_crash_during_restore_is_rolled_back_on_next_start(restore_env, replace, crash_at, before, crash_in_db):
    tmp_path, workspace, db, archive = restore_env
    old = _state(workspace)
    _run_crashing(RESTORE_CRASH, archive=str(archive), db=str(db), workspace=str(workspace),
                  backups=str(tmp_path / "backups"), replace=replace, crash_at=crash_at, before=before,
                  crash_in_db=crash_in_db)
    assert list(tmp_path.glob(".workspace-restore-*"))                   # Reste des Absturzes

    assert recover_interrupted_restores(workspace) == 1
    assert _state(workspace) == old                                      # alter Workspace ...
    assert _marker(db) == "alte db"                                      # ... passend zur alten DB
    assert not list(tmp_path.glob(".workspace-restore-*"))
    assert list((tmp_path / "backups").glob("conclave-pre-restore-*"))   # Sicherheits-Backup bleibt


def test_restore_after_a_crash_cleans_up_and_succeeds(restore_env):
    tmp_path, workspace, db, archive = restore_env
    _run_crashing(RESTORE_CRASH, archive=str(archive), db=str(db), workspace=str(workspace),
                  backups=str(tmp_path / "backups"), replace=True, crash_at=1, before=False, crash_in_db=False)
    from conclave.runtime.backup import restore_backup_archive
    restore_backup_archive(backup_path=archive, db_path=db, workspace_root=workspace,
                           backup_dir=tmp_path / "backups", secret=b"geheim")
    assert _state(workspace) == [("notes/beide.md", "neu"), ("notes/neu.md", "neu")]
    assert _marker(db) == "neue db"
    assert not list(tmp_path.glob(".workspace-restore-*"))


def test_running_restore_of_another_process_is_left_alone(restore_env):
    tmp_path, workspace, _, _ = restore_env
    staging = tmp_path / ".workspace-restore-laufend"
    staging.mkdir()
    (staging / "owner").write_text(str(os.getpid()), encoding="utf-8")   # dieser Prozess lebt
    (staging / "journal.json").write_text(json.dumps({"mode": "replace", "files": ["x"]}), encoding="utf-8")
    assert recover_interrupted_restores(workspace) == 0
    assert staging.is_dir()


def test_finished_restore_leftovers_are_only_cleaned_up(restore_env):
    tmp_path, workspace, _, _ = restore_env
    old = _state(workspace)
    staging = tmp_path / ".workspace-restore-fertig"
    (staging / "previous").mkdir(parents=True)
    (staging / "owner").write_text("999999999", encoding="utf-8")
    (staging / "journal.json").write_text(json.dumps({"mode": "replace", "files": ["x"]}), encoding="utf-8")
    (staging / "done").write_text("", encoding="utf-8")
    assert recover_interrupted_restores(workspace) == 0
    assert not staging.exists() and _state(workspace) == old


def test_server_start_rolls_back_a_crashed_restore(restore_env, monkeypatch):
    from conclave.api.server import _build_app
    from conclave.cli.config import ConclaveConfig
    tmp_path, workspace, db, archive = restore_env
    old = _state(workspace)
    _run_crashing(RESTORE_CRASH, archive=str(archive), db=str(db), workspace=str(workspace),
                  backups=str(tmp_path / "backups"), replace=True, crash_at=1, before=False, crash_in_db=False)
    assert not workspace.exists()                                        # so laesst der Absturz es zurueck
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(workspace))
    _build_app(ConclaveConfig(db_path=tmp_path / "server.db", api_key="cvh_x", agent_api_key="cva_y"))
    assert _state(workspace) == old
