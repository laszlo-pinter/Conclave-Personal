from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_ci_workflow_exists():
    assert WORKFLOW.exists()


def test_ci_runs_personal_matrix_on_windows_and_linux():
    text = _workflow_text()

    assert "ubuntu-latest" in text
    assert "windows-latest" in text
    assert '"3.11"' in text
    assert '"3.12"' in text
    assert "python -m pytest" in text


def test_ci_builds_and_inspects_release_artifacts():
    text = _workflow_text()

    assert "python -m build --sdist --wheel" in text
    assert "conclave-ui.html" in text
    assert "static/openapi.json" in text
    assert "entry_points.txt" in text
    assert "__pycache__" in text
    assert "workspace/" in text


def test_ci_does_not_use_real_provider_secrets():
    text = _workflow_text()
    forbidden = [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "MISTRAL_API_KEY",
        "DASHSCOPE_API_KEY",
        "secrets.",
    ]

    for token in forbidden:
        assert token not in text
