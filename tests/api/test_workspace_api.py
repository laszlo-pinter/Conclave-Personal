# tests/api/test_workspace_api.py
#
# Rote Tests: Pfadschutz in GET/POST/DELETE /workspace/<path>

import os
import pytest
pytest.importorskip("flask")

from unittest.mock import MagicMock
from conclave.api.app import create_app
from conclave.cli.handler import CLIResult


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "notes.txt").write_text("Workspace-Inhalt")
    (ws / ".private").mkdir()
    (ws / ".private" / "secret.txt").write_text("SECRET")
    return ws


@pytest.fixture
def outside_file(tmp_path):
    f = tmp_path / "secret.txt"
    f.write_text("TOP SECRET")
    return f


@pytest.fixture
def handler():
    h = MagicMock()
    h.list_conversations.return_value = CLIResult(success=True, message="ok", data={"conversations": []})
    return h


@pytest.fixture
def client(handler, workspace, monkeypatch):
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(workspace))
    app = create_app(handler)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ── GET /workspace/<path> ─────────────────────────────────────────────────────

class TestWorkspaceReadPathTraversal:

    def test_absolute_path_read_is_blocked(self, client, outside_file):
        """GET /workspace/<absoluter Pfad> muss 403 zurückgeben."""
        # Flask <path:> nimmt den Pfad nach /workspace/ - absolute Pfade
        # können über doppelten Slash encoded ankommen
        resp = client.get(f"/workspace/{str(outside_file).lstrip('/')}")
        # Entweder 403 (Pfad verboten) oder 404 (außerhalb Workspace)
        # Kritisch: darf nicht 200 mit Inhalt sein
        assert resp.status_code in (403, 404)
        if resp.status_code == 200:
            data = resp.get_json()
            assert "TOP SECRET" not in data.get("content", "")

    def test_traversal_read_is_blocked(self, client):
        """GET /workspace/../../etc/passwd muss 403 zurückgeben."""
        resp = client.get("/workspace/../../etc/passwd")
        assert resp.status_code == 403

    def test_legitimate_read_works(self, client):
        """GET /workspace/notes.txt muss 200 mit Inhalt zurückgeben."""
        resp = client.get("/workspace/notes.txt")
        assert resp.status_code == 200
        assert resp.get_json()["content"] == "Workspace-Inhalt"

    def test_hidden_file_read_is_blocked(self, client):
        resp = client.get("/workspace/.private/secret.txt")
        assert resp.status_code == 404

    def test_large_file_read_is_blocked(self, client, workspace, monkeypatch):
        monkeypatch.setenv("CONCLAVE_WORKSPACE_UI_READ_LIMIT_BYTES", "8")
        (workspace / "large.txt").write_text("zu viel text", encoding="utf-8")

        resp = client.get("/workspace/large.txt")

        assert resp.status_code == 413


# ── POST /workspace/<path> ────────────────────────────────────────────────────

class TestWorkspaceWritePathTraversal:

    def test_nested_path_stays_inside_workspace(self, client, workspace, tmp_path):
        """POST mit tief-verschachteltem Pfad darf den Workspace nicht verlassen.

        Flask <path:filepath> stripped führende '/', daher ist ein echter
        absoluter-Pfad-Angriff über die URL-Route nicht möglich. Wir stellen
        sicher, dass auch verschachtelte Pfade innerhalb WORKSPACE bleiben.
        """
        resp = client.post("/workspace/subdir/new.txt", json={"content": "Hallo"})
        assert resp.status_code == 201
        # Datei muss innerhalb des Workspace liegen
        written = workspace / "subdir" / "new.txt"
        assert written.exists()
        # Nichts darf außerhalb tmp_path/workspace angelegt worden sein
        evil = tmp_path / "subdir" / "new.txt"
        assert not evil.exists()

    def test_traversal_write_is_blocked(self, client, tmp_path):
        """POST /workspace/../../evil.txt muss 403 zurückgeben."""
        resp = client.post("/workspace/../../evil.txt", json={"content": "EVIL"})
        assert resp.status_code == 403

    def test_legitimate_write_works(self, client, workspace):
        """POST /workspace/new.txt schreibt korrekt in den Workspace."""
        resp = client.post("/workspace/new.txt", json={"content": "Hallo"})
        assert resp.status_code == 201
        assert (workspace / "new.txt").exists()

    def test_hidden_write_is_blocked(self, client, workspace):
        resp = client.post("/workspace/.private/new.txt", json={"content": "nope"})
        assert resp.status_code == 403
        assert not (workspace / ".private" / "new.txt").exists()

    def test_large_write_is_blocked(self, client, workspace, monkeypatch):
        monkeypatch.setenv("CONCLAVE_WORKSPACE_WRITE_LIMIT_BYTES", "4")

        resp = client.post("/workspace/new.txt", json={"content": "Hallo"})

        assert resp.status_code == 413
        assert not (workspace / "new.txt").exists()


# ── DELETE /workspace/<path> ──────────────────────────────────────────────────

class TestWorkspaceDeletePathTraversal:

    def test_traversal_delete_is_blocked(self, client):
        """DELETE /workspace/../../notes.txt muss 403 zurückgeben."""
        resp = client.delete("/workspace/../../notes.txt")
        assert resp.status_code == 403

    def test_hidden_delete_is_blocked(self, client, workspace):
        resp = client.delete("/workspace/.private/secret.txt")
        assert resp.status_code == 403
        assert (workspace / ".private" / "secret.txt").exists()


def test_workspace_listing_hides_hidden_files(client):
    resp = client.get("/workspace")

    paths = {item["path"] for item in resp.get_json()["files"]}
    assert "notes.txt" in paths
    assert ".private/secret.txt" not in paths
