from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_license_file_exists_and_pyproject_declares_polyform_noncommercial():
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "PolyForm Noncommercial License 1.0.0" in license_text
    assert 'license = "LicenseRef-PolyForm-Noncommercial-1.0.0"' in pyproject
    assert 'license-files = ["LICENSE"]' in pyproject


def test_release_docs_exist():
    required = [
        "docs/sicherheit.md",
        "docs/beispiel-workflows.md",
        "docs/release-notes-v0.1.3.md",
        "docs/release-notes-v0.1.2.md",
        "docs/release-notes-v0.1.1.md",
        "docs/release-notes-v0.1.0.md",
        "docs/index.md",
    ]

    for relative in required:
        assert (ROOT / relative).is_file()


def test_release_screenshots_exist():
    screenshots = [
        ROOT / "docs/assets/screenshots/conclave-studio-desktop.png",
        ROOT / "docs/assets/screenshots/conclave-agents-desktop.png",
    ]

    for screenshot in screenshots:
        assert screenshot.is_file()
        assert screenshot.stat().st_size > 10_000


def test_readme_links_release_material():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "docs/assets/screenshots/conclave-studio-desktop.png" in readme
    assert "docs/beispiel-workflows.md" in readme
    assert "docs/sicherheit.md" in readme
    assert "PolyForm Noncommercial License 1.0.0" in readme


def test_release_docs_use_publishable_distribution_name():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    release_notes = (ROOT / "docs/release-notes-v0.1.3.md").read_text(encoding="utf-8")
    combined = readme + "\n" + release_notes

    assert "pipx install conclave-personal" in combined
    assert "conclave_personal-0.1.3-py3-none-any.whl" in combined
    assert "pipx install conclave\n" not in combined
    assert "conclave-0.1.0-py3-none-any.whl" not in combined
    assert "conclave-0.1.1-py3-none-any.whl" not in combined
    assert "conclave-0.1.2-py3-none-any.whl" not in combined
    assert "conclave-0.1.3-py3-none-any.whl" not in combined


def test_readme_describes_published_install_path():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Das veröffentlichte Paket heißt `conclave-personal`" in readme
    assert "Nach der PyPI-Veröffentlichung ist der Zielpfad" not in readme
    assert "Vor der PyPI-Veröffentlichung wird" not in readme
    assert "wird vor Veröffentlichung" not in readme
    assert "Lokale Artefakte können direkt aus einem frisch gebauten Wheel geprüft werden" not in readme
    assert ".venv-smoke/Scripts/pip install" not in readme
