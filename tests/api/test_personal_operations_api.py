import pytest
pytest.importorskip("flask")

from pathlib import Path
from unittest.mock import MagicMock
import zipfile

from conclave.api.app import create_app
from conclave.cli.config import ConclaveConfig
from conclave.cli.handler import CLIResult


@pytest.fixture
def handler():
    h = MagicMock()
    h.delete_participant.return_value = CLIResult(
        success=True, message="ok", data={"participant_id": "p1"}
    )
    return h


@pytest.fixture
def client(handler, tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(workspace))
    config = ConclaveConfig(db_path=tmp_path / "conclave.db", openai_api_key="sk-test")
    config.db_path.write_text("sqlite bytes", encoding="utf-8")
    app = create_app(handler, config=config)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_health_returns_ok(client):
    resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_providers_returns_presets_without_secret_values(client):
    resp = client.get("/providers")

    body = resp.get_json()
    assert resp.status_code == 200
    assert any(p["name"] == "openai" for p in body["providers"])
    assert "sk-test" not in resp.get_data(as_text=True)


def test_providers_return_personal_status_fields(client):
    resp = client.get("/providers")

    providers = {p["name"]: p for p in resp.get_json()["providers"]}
    assert providers["openai"]["requires_api_key"] is True
    assert providers["openai"]["api_key_env"] == "OPENAI_API_KEY"
    assert providers["openai"]["api_key_configured"] is True
    assert providers["ollama"]["requires_api_key"] is False
    assert providers["ollama"]["local"] is True


def test_agent_roles_returns_personal_roles(client):
    resp = client.get("/agent-roles")

    body = resp.get_json()
    assert resp.status_code == 200
    ids = {role["id"] for role in body["roles"]}
    assert {"writer", "reviewer", "critic", "researcher", "planner", "custom"} <= ids
    assert "judge" not in ids


def test_settings_get_returns_runtime_settings(client):
    resp = client.get("/settings")

    body = resp.get_json()["settings"]
    assert resp.status_code == 200
    assert body["db_provider"] == "sqlite"
    assert body["provider_keys"]["openai"] is True
    assert body["workspace_limits"]["hidden_paths_visible"] is False
    assert body["workspace_limits"]["agent_read_bytes"] > 0


def test_settings_put_updates_workspace_path(client, tmp_path):
    new_workspace = tmp_path / "new-workspace"

    resp = client.put("/settings", json={"workspace_path": str(new_workspace)})

    assert resp.status_code == 200
    assert Path(resp.get_json()["settings"]["workspace_path"]) == new_workspace
    assert new_workspace.exists()


def test_backup_creates_zip(client, tmp_path, monkeypatch):
    backup_dir = tmp_path / "backups"
    monkeypatch.setenv("CONCLAVE_BACKUP_DIR", str(backup_dir))

    resp = client.post("/backup")

    assert resp.status_code == 201
    backup_path = Path(resp.get_json()["backup_path"])
    assert backup_path.exists()
    assert backup_path.suffix == ".zip"


def test_restore_rejects_invalid_archive(client, tmp_path):
    backup_path = tmp_path / "backup.zip"
    backup_path.write_text("not really a zip", encoding="utf-8")

    resp = client.post("/restore", json={"backup_path": str(backup_path)})

    assert resp.status_code == 400
    assert resp.get_json()["status"] == "invalid_backup"


def test_restore_restores_db_and_replaces_workspace(handler, tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "old.txt").write_text("old workspace", encoding="utf-8")
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(workspace))
    backup_dir = tmp_path / "backups"
    monkeypatch.setenv("CONCLAVE_BACKUP_DIR", str(backup_dir))
    db_path = tmp_path / "conclave.db"
    db_path.write_text("old db", encoding="utf-8")

    backup_path = tmp_path / "restore.zip"
    with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("conclave.db", "restored db")
        zf.writestr("workspace/notes/restored.md", "restored workspace")

    config = ConclaveConfig(db_path=db_path, openai_api_key="sk-test")
    app = create_app(handler, config=config)
    app.config["TESTING"] = True

    with app.test_client() as c:
        resp = c.post("/restore", json={"backup_path": str(backup_path)})

    body = resp.get_json()
    assert resp.status_code == 200
    assert body["status"] == "restored"
    assert body["db_restored"] is True
    assert body["workspace_files_restored"] == 1
    assert body["workspace_replaced"] is True
    assert Path(body["pre_restore_backup_path"]).is_file()
    assert db_path.read_text(encoding="utf-8") == "restored db"
    assert (workspace / "notes" / "restored.md").read_text(encoding="utf-8") == "restored workspace"
    assert not (workspace / "old.txt").exists()


def test_restore_rejects_zip_slip_path(handler, tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(workspace))
    db_path = tmp_path / "conclave.db"
    db_path.write_text("old db", encoding="utf-8")
    backup_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(backup_path, "w") as zf:
        zf.writestr("workspace/../escape.txt", "nope")

    app = create_app(handler, config=ConclaveConfig(db_path=db_path))
    app.config["TESTING"] = True

    with app.test_client() as c:
        resp = c.post("/restore", json={"backup_path": str(backup_path)})

    assert resp.status_code == 400
    assert resp.get_json()["status"] == "invalid_backup"
    assert not (tmp_path / "escape.txt").exists()


def test_delete_participant_endpoint(client, handler):
    resp = client.delete("/conversations/conv-1/participants/p1")

    assert resp.status_code == 204
    handler.delete_participant.assert_called_once_with("conv-1", "p1")
