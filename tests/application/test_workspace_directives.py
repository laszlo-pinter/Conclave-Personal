# tests/application/test_workspace_directives.py
#
# Rote Tests: Pfadschutz in _expand_workspace_refs und _process_agent_directives.
# Alle drei Angriffsvektoren:
#   1. Absoluter Pfad: @workspace//etc/passwd  → /etc/passwd (WORKSPACE wird ignoriert)
#   2. Relativer Traversal: @workspace/../../etc/passwd  → bereits geblockt, aber Regression
#   3. @save(/böser/pfad) in Agent-Antwort
#   4. @read(/böser/pfad) in Agent-Antwort

import os

import pytest

from conclave.application.conversation_flow import ConversationFlowService
from conclave.domain.conversation import Conversation


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def workspace(tmp_path):
    """Echtes Workspace-Verzeichnis mit einer harmlosen Datei."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "readme.txt").write_text("Hallo Workspace")
    (ws / ".private").mkdir()
    (ws / ".private" / "secret.txt").write_text("SECRET")
    yield ws


@pytest.fixture
def outside_file(tmp_path):
    """Datei außerhalb des Workspace."""
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP SECRET")
    return secret


@pytest.fixture
def conversation():
    return Conversation.create()


# ── _expand_workspace_refs ────────────────────────────────────────────────────

class TestExpandWorkspaceRefsPathTraversal:

    def test_absolute_path_is_blocked(self, workspace, outside_file, conversation, monkeypatch):
        """@workspace//etc/passwd → absoluter Pfad darf WORKSPACE nicht verlassen."""
        monkeypatch.setenv("CONCLAVE_WORKSPACE", str(workspace))
        # Simuliert @workspace/ gefolgt von absolutem Pfad (führende /)
        conversation.add_user_message(f"Lies @workspace/{outside_file}")
        result = ConversationFlowService._expand_workspace_refs(conversation)
        assert "TOP SECRET" not in result.messages[0].content
        assert "FEHLER" in result.messages[0].content

    def test_relative_traversal_is_blocked(self, workspace, outside_file, conversation, monkeypatch):
        """@workspace/../../secret.txt → normpath ergibt '../..', muss geblockt werden."""
        monkeypatch.setenv("CONCLAVE_WORKSPACE", str(workspace))
        conversation.add_user_message("Lies @workspace/../../secret.txt")
        result = ConversationFlowService._expand_workspace_refs(conversation)
        assert "TOP SECRET" not in result.messages[0].content
        assert "FEHLER" in result.messages[0].content

    def test_legitimate_path_still_works(self, workspace, conversation, monkeypatch):
        """Normaler Zugriff auf workspace/readme.txt bleibt funktionsfähig."""
        monkeypatch.setenv("CONCLAVE_WORKSPACE", str(workspace))
        conversation.add_user_message("Lies @workspace/readme.txt")
        result = ConversationFlowService._expand_workspace_refs(conversation)
        assert "Hallo Workspace" in result.messages[0].content

    def test_hidden_path_is_invisible(self, workspace, conversation, monkeypatch):
        monkeypatch.setenv("CONCLAVE_WORKSPACE", str(workspace))
        conversation.add_user_message("Lies @workspace/.private/secret.txt")

        result = ConversationFlowService._expand_workspace_refs(conversation)

        assert "SECRET" not in result.messages[0].content
        assert "FEHLER" in result.messages[0].content

    def test_large_workspace_ref_is_blocked(self, workspace, conversation, monkeypatch):
        monkeypatch.setenv("CONCLAVE_WORKSPACE", str(workspace))
        monkeypatch.setenv("CONCLAVE_WORKSPACE_AGENT_READ_LIMIT_BYTES", "8")
        (workspace / "large.txt").write_text("zu viel text", encoding="utf-8")
        conversation.add_user_message("Lies @workspace/large.txt")

        result = ConversationFlowService._expand_workspace_refs(conversation)

        assert "zu viel text" not in result.messages[0].content
        assert "zu gross" in result.messages[0].content


# ── _process_agent_directives: @save ─────────────────────────────────────────

class TestProcessAgentDirectivesSavePathTraversal:

    def test_save_with_absolute_path_is_blocked(self, workspace, monkeypatch):
        """@save(/etc/cron.d/backdoor) darf keine Datei außerhalb des Workspace schreiben."""
        monkeypatch.setenv("CONCLAVE_WORKSPACE", str(workspace))
        # Sicherstellen dass keine Datei von einem früheren Lauf übrig ist
        import tempfile
        target = os.path.join(tempfile.gettempdir(), "conclave_traversal_test.txt")
        if os.path.exists(target):
            os.remove(target)
        content = f"@save({target})\nbash -i\n@endsave"
        result = ConversationFlowService._process_agent_directives(content)
        # Funktion muss FEHLER melden und DARF die Datei nicht angelegt haben
        assert "FEHLER" in result
        assert not os.path.exists(target), f"Datei außerhalb Workspace wurde angelegt: {target}"

    def test_save_with_traversal_is_blocked(self, workspace, tmp_path, monkeypatch):
        """@save(../../evil.sh) darf keine Datei außerhalb des Workspace/output/ schreiben."""
        monkeypatch.setenv("CONCLAVE_WORKSPACE", str(workspace))
        evil_path = tmp_path / "evil.sh"
        content = "@save(../../evil.sh)\nmalicious\n@endsave"
        result = ConversationFlowService._process_agent_directives(content)
        assert not evil_path.exists()
        assert "FEHLER" in result

    def test_save_legitimate_path_still_works(self, workspace, monkeypatch):
        """@save(report.md) schreibt korrekt in workspace/output/."""
        monkeypatch.setenv("CONCLAVE_WORKSPACE", str(workspace))
        content = "@save(report.md)\n# Bericht\n@endsave"
        result = ConversationFlowService._process_agent_directives(content)
        assert "gespeichert" in result
        assert (workspace / "output" / "report.md").exists()

    def test_save_large_file_is_blocked(self, workspace, monkeypatch):
        monkeypatch.setenv("CONCLAVE_WORKSPACE", str(workspace))
        monkeypatch.setenv("CONCLAVE_WORKSPACE_WRITE_LIMIT_BYTES", "8")
        content = "@save(report.md)\nzu viel text\n@endsave"

        result = ConversationFlowService._process_agent_directives(content)

        assert "zu gross" in result
        assert not (workspace / "output" / "report.md").exists()


# ── _process_agent_directives: @read ─────────────────────────────────────────

class TestProcessAgentDirectivesReadPathTraversal:

    def test_read_with_absolute_path_is_blocked(self, workspace, outside_file, monkeypatch):
        """@read(/tmp/secret.txt) darf nicht gelesen werden."""
        monkeypatch.setenv("CONCLAVE_WORKSPACE", str(workspace))
        content = f"@read({outside_file})"
        result = ConversationFlowService._process_agent_directives(content)
        assert "TOP SECRET" not in result
        assert "FEHLER" in result

    def test_read_with_traversal_is_blocked(self, workspace, monkeypatch):
        """@read(../../etc/passwd) darf nicht gelesen werden."""
        monkeypatch.setenv("CONCLAVE_WORKSPACE", str(workspace))
        content = "@read(../../etc/passwd)"
        result = ConversationFlowService._process_agent_directives(content)
        assert "FEHLER" in result

    def test_read_hidden_path_is_blocked(self, workspace, monkeypatch):
        monkeypatch.setenv("CONCLAVE_WORKSPACE", str(workspace))
        content = "@read(.private/secret.txt)"

        result = ConversationFlowService._process_agent_directives(content)

        assert "SECRET" not in result
        assert "FEHLER" in result

    def test_read_large_file_is_blocked(self, workspace, monkeypatch):
        monkeypatch.setenv("CONCLAVE_WORKSPACE", str(workspace))
        monkeypatch.setenv("CONCLAVE_WORKSPACE_AGENT_READ_LIMIT_BYTES", "8")
        (workspace / "large.txt").write_text("zu viel text", encoding="utf-8")

        result = ConversationFlowService._process_agent_directives("@read(large.txt)")

        assert "zu viel text" not in result
        assert "zu gross" in result
