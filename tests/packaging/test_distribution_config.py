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


def test_distribution_name_avoids_reserved_pypi_project():
    project = _pyproject()["project"]

    assert project["name"] == "conclave-personal"


def test_distribution_metadata_links_back_to_project():
    project = _pyproject()["project"]
    urls = project["urls"]

    assert project["authors"] == [{"name": "Laszlo Pinter"}]
    assert urls["Homepage"] == "https://github.com/laszlo-pinter/Conclave-Personal"
    assert urls["Source"] == "https://github.com/laszlo-pinter/Conclave-Personal"
    assert urls["Issues"] == "https://github.com/laszlo-pinter/Conclave-Personal/issues"
    assert urls["Documentation"].endswith("/docs/index.md")
    assert urls["Changelog"].endswith("/docs/release-notes-v0.1.2.md")


def test_console_scripts_are_declared():
    scripts = _pyproject()["project"]["scripts"]

    assert scripts["conclave"] == "conclave.cli.main:main"
    assert scripts["conclave-api"] == "conclave.api.server:main"
    assert scripts["conclave-mcp"] == "conclave.mcp_server:main"


def test_distribution_package_data_include_ui_and_platform_scripts():
    setuptools_config = _pyproject()["tool"]["setuptools"]
    package_data = setuptools_config["package-data"]["conclave"]

    assert "data-files" not in setuptools_config
    assert "assets/conclave-ui.html" in package_data
    assert "assets/static/css/*.css" in package_data
    assert "assets/static/js/*.js" in package_data
    assert "assets/static/js/features/*.js" in package_data
    assert "assets/scripts/windows/*.ps1" in package_data
    assert "assets/scripts/linux/*" in package_data


def test_manifest_excludes_local_runtime_data():
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    assert "recursive-exclude workspace *" in manifest
    assert "global-exclude __pycache__ *.py[cod] *.db *.db-shm *.db-wal *.key *.pem *.log" in manifest


def test_manifest_includes_release_material():
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    assert "include LICENSE" in manifest
    assert "recursive-include src/conclave/assets *" in manifest
    assert "include docs/sicherheit.md" in manifest
    assert "include docs/beispiel-workflows.md" in manifest
    assert "include docs/release-notes-v0.1.0.md" in manifest
    assert "include docs/release-notes-v0.1.1.md" in manifest
    assert "include docs/release-notes-v0.1.2.md" in manifest
    assert "recursive-include docs/assets/screenshots *.png" not in manifest
