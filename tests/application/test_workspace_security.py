from pathlib import Path

from conclave.application.workspace_security import (
    is_hidden_workspace_path,
    resolve_output_path,
    resolve_workspace_path,
)


def test_resolve_workspace_path_blocks_absolute_path(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()

    assert resolve_workspace_path(str(tmp_path / "secret.txt"), root=root) is None


def test_resolve_workspace_path_blocks_traversal(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()

    assert resolve_workspace_path("../secret.txt", root=root) is None


def test_resolve_output_path_stays_in_output(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()

    assert resolve_output_path("../secret.txt", root=root) is None
    resolved = resolve_output_path("reports/a.md", root=root)

    assert resolved is not None
    assert resolved.relative == "output/reports/a.md"


def test_hidden_workspace_path_detects_hidden_component(tmp_path):
    root = tmp_path / "workspace"
    hidden = root / ".private" / "notes.md"

    assert is_hidden_workspace_path(hidden, root=root)
