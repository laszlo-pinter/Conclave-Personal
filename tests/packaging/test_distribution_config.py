import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_base_install_has_desktop_runtime_dependencies():
    project = _pyproject()["project"]
    deps = set(project["dependencies"])

    assert "flask>=3.0" in deps
    assert "flask-limiter>=4.0" in deps
    assert "cryptography>=42.0" in deps


def test_console_scripts_are_declared():
    scripts = _pyproject()["project"]["scripts"]

    assert scripts["conclave"] == "conclave.cli.main:main"
    assert scripts["conclave-api"] == "conclave.api.server:main"
    assert scripts["conclave-mcp"] == "conclave.mcp_server:main"


def test_distribution_data_files_include_ui_and_platform_scripts():
    data_files = _pyproject()["tool"]["setuptools"]["data-files"]

    assert "conclave-ui.html" in data_files["share/conclave"]
    assert "static/css/*.css" in data_files["share/conclave/static/css"]
    assert "static/js/features/*.js" in data_files["share/conclave/static/js/features"]
    assert "scripts/windows/*.ps1" in data_files["share/conclave/scripts/windows"]
    assert "scripts/linux/*" in data_files["share/conclave/scripts/linux"]


def test_manifest_excludes_local_runtime_data():
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    assert "recursive-exclude workspace *" in manifest
    assert "global-exclude __pycache__ *.py[cod] *.db *.db-shm *.db-wal *.key *.pem *.log" in manifest


def test_manifest_includes_release_material():
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    assert "include LICENSE" in manifest
    assert "include docs/sicherheit.md" in manifest
    assert "include docs/beispiel-workflows.md" in manifest
    assert "include docs/release-notes-v0.1.0.md" in manifest
    assert "recursive-include docs/assets/screenshots *.png" in manifest
