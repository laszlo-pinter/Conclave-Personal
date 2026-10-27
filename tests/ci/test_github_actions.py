from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
PUBLISH_WORKFLOW = ROOT / ".github" / "workflows" / "publish.yml"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_ci_workflow_exists():
    assert WORKFLOW.exists()
    assert PUBLISH_WORKFLOW.exists()


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
    assert "conclave/assets/conclave-ui.html" in text
    assert "conclave/assets/static/openapi.json" in text
    assert "conclave/assets/static/vendor/purify.min.js" in text
    assert "conclave/assets/static/vendor/marked.min.js" in text
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


def test_workflows_use_runner_context_only_in_steps():
    for workflow in (WORKFLOW, PUBLISH_WORKFLOW):
        text = workflow.read_text(encoding="utf-8")
        before_steps = text.split("    steps:", 1)[0]
        assert "runner.temp" not in before_steps


def test_publish_workflow_uses_trusted_publishing():
    text = PUBLISH_WORKFLOW.read_text(encoding="utf-8")

    assert 'tags:' in text
    assert '- "v*"' in text
    assert "environment:" in text
    assert "name: pypi" in text
    assert "id-token: write" in text
    assert "pypa/gh-action-pypi-publish@7245906fb61fa33a13554f9d5fb856fe61758086 # v1.14.3" in text
    assert "secrets." not in text


def test_publish_workflow_builds_conclave_personal_artifacts():
    text = PUBLISH_WORKFLOW.read_text(encoding="utf-8")

    assert "python -m build --sdist --wheel" in text
    assert "dist/conclave_personal-0.4.0-py3-none-any.whl" in text
    assert "dist/conclave_personal-0.4.0.tar.gz" in text


def test_ci_runs_ui_browser_tests_strictly():
    text = _workflow_text()
    job = text.split("  ui-browser:", 1)[1].split("\n  build:", 1)[0]

    assert 'CONCLAVE_REQUIRE_BROWSER: "1"' in job
    assert '".[dev-all,dev-ui]"' in job
    assert "python -m playwright install --with-deps chromium" in job
    assert "python -m pytest tests/ui" in job


def test_all_actions_are_pinned_to_commit_sha():
    """AP 7: Actions nur ueber unveraenderliche Commit-SHAs (Lieferkette)."""
    import re

    for workflow in (WORKFLOW, PUBLISH_WORKFLOW):
        for line in workflow.read_text(encoding="utf-8").splitlines():
            if "uses:" not in line:
                continue
            ref = line.split("uses:", 1)[1].split("#", 1)[0].strip()
            assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), f"{workflow.name}: nicht gepinnt: {ref}"
            assert "# v" in line, f"{workflow.name}: Versionskommentar fehlt: {line.strip()}"


def test_ci_runs_security_checks():
    text = _workflow_text()
    job = text.split("  security:", 1)[1].split("\n  build:", 1)[0]

    assert '".[dev-all,dev-ui,dev-security]"' in job
    assert "python -m pip_audit --skip-editable" in job
    assert "python -m bandit -r src/conclave --severity-level medium" in job


def test_ci_runs_postgres_tests_against_pinned_image():
    text = _workflow_text()
    job = text.split("  postgres:", 1)[1].split("\n  build:", 1)[0]

    assert "image: postgres@sha256:" in job                     # Image per Digest gepinnt
    assert "pg_isready" in job                                   # erst testen, wenn Postgres bereit ist
    assert "CONCLAVE_TEST_POSTGRES_DSN:" in job
    assert "python -m pytest tests/persistence" in job
