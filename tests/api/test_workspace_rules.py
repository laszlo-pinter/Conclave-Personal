"""R8 (conclave#43): Workspace-Regeln.

- Agenten legen nur neue Dateien an oder schreiben unter agents/; vorhandene Dateien
  ueberschreibt nur der Mensch. conclave_notify.json ist fuer Agenten gesperrt.
- Pfadkomponenten mit ':' , Geraetenamen, Punkt/Leerzeichen am Ende werden abgelehnt.
- Der Workspace darf Home-, Konfigurations-, Daten-, Log- oder Backup-Verzeichnis nicht enthalten.
- Schreiben prueft den Typ und ist atomar (temporaere Datei, dann os.replace).
"""

import os

import pytest

pytest.importorskip("flask")

from conclave.application import workspace_security as ws  # noqa: E402
from conclave.cli.config import ConclaveConfig  # noqa: E402

HUMAN = "cvh_mensch-token"
AGENT = "cva_agent-token"


@pytest.fixture
def env(tmp_path, monkeypatch):
    from conclave.api.server import _build_app

    workspace = tmp_path / "home" / "Conclave" / "workspace"
    workspace.mkdir(parents=True)
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "home" / "AppData" / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "home" / "AppData" / "Local"))
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(workspace))
    monkeypatch.setenv("CONCLAVE_SECRET_KEY_FILE", str(tmp_path / "cfg" / "secret.key"))
    monkeypatch.setenv("CONCLAVE_API_TOKEN_FILE", str(tmp_path / "cfg" / "api.token"))
    monkeypatch.setenv("CONCLAVE_AGENT_TOKEN_FILE", str(tmp_path / "cfg" / "agent.token"))
    monkeypatch.setenv("CONCLAVE_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.delenv("CONCLAVE_API_KEY", raising=False)
    monkeypatch.delenv("CONCLAVE_AGENT_KEY", raising=False)
    app, _ = _build_app(ConclaveConfig(db_path=tmp_path / "data" / "c.db", api_key=HUMAN, agent_api_key=AGENT))
    app.config["TESTING"] = True
    client = app.test_client()

    class Env:
        pass

    e = Env()
    e.tmp, e.workspace, e.client = tmp_path, workspace, client
    e.human = {"Authorization": f"Bearer {HUMAN}"}
    e.agent = {"Authorization": f"Bearer {AGENT}"}
    return e


def _write(env, who, path, content):
    return env.client.post(f"/workspace/{path}", json={"content": content}, headers=getattr(env, who))


# ── Agenten: nur neue Dateien, agents/ frei ─────────────────────────────────

def test_agent_cannot_overwrite_an_existing_file(env):
    (env.workspace / "plan.md").write_text("vom Menschen", encoding="utf-8")
    resp = _write(env, "agent", "plan.md", "")
    assert resp.status_code == 403
    assert (env.workspace / "plan.md").read_text(encoding="utf-8") == "vom Menschen"


def test_agent_cannot_overwrite_files_in_the_conclave_folder(env):
    (env.workspace / "conclave").mkdir()
    (env.workspace / "conclave" / "plan.md").write_text("Plan", encoding="utf-8")
    assert _write(env, "agent", "conclave/plan.md", "anders").status_code == 403
    assert (env.workspace / "conclave" / "plan.md").read_text(encoding="utf-8") == "Plan"


def test_agent_creates_new_files(env):
    resp = _write(env, "agent", "reports/neu.md", "Bericht")
    assert resp.status_code == 201
    assert (env.workspace / "reports" / "neu.md").read_text(encoding="utf-8") == "Bericht"


def test_agent_may_overwrite_below_agents(env):
    assert _write(env, "agent", "agents/notizen.md", "eins").status_code == 201
    assert _write(env, "agent", "agents/notizen.md", "zwei").status_code == 201
    assert (env.workspace / "agents" / "notizen.md").read_text(encoding="utf-8") == "zwei"


def test_agent_cannot_write_the_notify_marker(env):
    assert _write(env, "agent", "conclave_notify.json", "{}").status_code == 403
    assert not (env.workspace / "conclave_notify.json").exists()


@pytest.mark.parametrize("name", ["Conclave_Notify.json", "CONCLAVE_NOTIFY.JSON", "conclave_Notify.json"])
def test_agent_cannot_write_the_notify_marker_in_another_case(env, name):
    assert _write(env, "agent", name, "{}").status_code == 403
    assert not any(p.name.lower() == "conclave_notify.json" for p in env.workspace.iterdir())


@pytest.mark.skipif(os.name == "nt", reason="POSIX-Dateirechte")
def test_atomic_write_keeps_the_file_mode(env):
    target = env.workspace / "plan.md"
    target.write_text("alt", encoding="utf-8")
    target.chmod(0o640)
    ws.write_text_atomic(target, "neu")
    assert (target.stat().st_mode & 0o777) == 0o640
    fresh = env.workspace / "neu.md"
    ws.write_text_atomic(fresh, "x")
    assert (fresh.stat().st_mode & 0o777) == (0o666 & ~ws._UMASK)


def test_output_path_rules_match_the_workspace_rules(env):
    assert ws.resolve_output_path(123, root=env.workspace) is None
    assert ws.resolve_output_path("a.txt:ads", root=env.workspace) is None
    assert ws.resolve_output_path("bericht.md", root=env.workspace) is not None


def test_human_overwrites_existing_files(env):
    (env.workspace / "plan.md").write_text("alt", encoding="utf-8")
    assert _write(env, "human", "plan.md", "neu").status_code == 201
    assert (env.workspace / "plan.md").read_text(encoding="utf-8") == "neu"


# ── Pfade ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    "a.txt:ads", "ok.txt::$DATA", "ENV~1:x", "CON", "con.txt", "nul", "NUL.md", "sub/COM1.log", "LPT9",
    "CONIN$", "datei.", "datei ", "ordner./x.md", "x\x01.md",
])
def test_unsafe_path_components_are_rejected(env, path):
    for who in ("human", "agent"):
        assert _write(env, who, path, "x").status_code in (400, 403), (who, path)
    assert ws.resolve_workspace_path(path, root=env.workspace) is None


@pytest.mark.parametrize("path", ["notes/console.md", "conference.txt", "a.b.c.md", "Null-Plan.md"])
def test_ordinary_names_stay_allowed(env, path):
    assert ws.resolve_workspace_path(path, root=env.workspace) is not None


def test_short_names_of_hidden_folders_are_rejected(env):
    assert ws.resolve_workspace_path("CONCLA~1/x.md", root=env.workspace) is None


# ── Schreiben: Typ und Atomaritaet ──────────────────────────────────────────

@pytest.mark.parametrize("content", [123, None, ["a"], {"a": 1}, True])
def test_non_text_content_is_rejected_and_leaves_the_file(env, content):
    (env.workspace / "plan.md").write_text("bleibt", encoding="utf-8")
    resp = env.client.post("/workspace/plan.md", json={"content": content}, headers=env.human)
    assert resp.status_code == 400
    assert (env.workspace / "plan.md").read_text(encoding="utf-8") == "bleibt"


def test_aborted_write_keeps_the_old_file(env, monkeypatch):
    (env.workspace / "plan.md").write_text("bleibt", encoding="utf-8")

    def broken_replace(src, dst):
        raise OSError("abgebrochen")

    monkeypatch.setattr(ws.os, "replace", broken_replace)
    with pytest.raises(OSError):
        ws.write_text_atomic(env.workspace / "plan.md", "neu")
    assert (env.workspace / "plan.md").read_text(encoding="utf-8") == "bleibt"
    assert [p.name for p in env.workspace.iterdir()] == ["plan.md"]     # keine Reste


def test_api_write_goes_through_the_atomic_helper(env, monkeypatch):
    (env.workspace / "plan.md").write_text("bleibt", encoding="utf-8")
    calls = []
    real = ws.write_text_atomic

    def spy(path, content, **kwargs):
        calls.append(path)
        return real(path, content, **kwargs)

    monkeypatch.setattr(ws, "write_text_atomic", spy)
    assert _write(env, "human", "plan.md", "neu").status_code == 201
    assert calls


# ── Workspace-Ort ───────────────────────────────────────────────────────────

def test_workspace_equal_to_home_is_rejected(env):
    resp = env.client.put("/settings", json={"workspace_path": str(env.tmp / "home")}, headers=env.human)
    assert resp.status_code == 400
    assert os.environ["CONCLAVE_WORKSPACE"] == str(env.workspace)


@pytest.mark.parametrize("sub", ["cfg", "data", "backups", "home/AppData", "."])
def test_workspace_containing_runtime_directories_is_rejected(env, sub):
    target = (env.tmp / sub).resolve()
    resp = env.client.put("/settings", json={"workspace_path": str(target)}, headers=env.human)
    assert resp.status_code == 400, sub
    assert os.environ["CONCLAVE_WORKSPACE"] == str(env.workspace)


def test_ordinary_workspace_is_accepted(env):
    target = env.tmp / "home" / "Projekte" / "ws"
    resp = env.client.put("/settings", json={"workspace_path": str(target)}, headers=env.human)
    assert resp.status_code == 200
    assert target.is_dir()


def test_server_refuses_to_start_with_home_as_workspace(env, monkeypatch, tmp_path):
    from conclave.api.server import _build_app
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(tmp_path / "home"))
    with pytest.raises(RuntimeError, match="Workspace"):
        _build_app(ConclaveConfig(db_path=tmp_path / "data" / "c2.db", api_key=HUMAN, agent_api_key=AGENT))


def test_token_files_inside_the_workspace_are_not_readable(env, monkeypatch):
    token = env.workspace / "geheim.token"
    token.write_text("cvh_x", encoding="utf-8")
    monkeypatch.setenv("CONCLAVE_API_TOKEN_FILE", str(token))
    assert ws.resolve_workspace_path("geheim.token", root=env.workspace) is None
    assert env.client.get("/workspace/geheim.token", headers=env.agent).status_code == 403
