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
        "docs/release-notes-v0.1.17.md",
        "docs/release-notes-v0.1.16.md",
        "docs/release-notes-v0.1.5.md",
        "docs/release-notes-v0.1.4.md",
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

    assert (
        "https://raw.githubusercontent.com/laszlo-pinter/Conclave-Personal/main/"
        "docs/assets/screenshots/conclave-studio-desktop.png"
    ) in readme
    assert "docs/beispiel-workflows.md" in readme
    assert "docs/sicherheit.md" in readme
    assert "PolyForm Noncommercial License 1.0.0" in readme


def test_readme_places_llm_origin_notice_as_section():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    lines = readme.splitlines()

    assert lines[0] == "# Conclave Personal"
    assert "## Origin" in readme
    assert "This project was created exclusively by LLM models." in readme
    assert lines[1].strip() != "> This project was created exclusively by LLM models."


def test_release_docs_use_publishable_distribution_name():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    release_notes = (ROOT / "docs/release-notes-v0.1.17.md").read_text(encoding="utf-8")
    combined = readme + "\n" + release_notes

    assert "pipx install conclave-personal" in combined
    assert "pipx install conclave\n" not in combined
    assert "conclave-0.1.0-py3-none-any.whl" not in combined
    assert "conclave-0.1.1-py3-none-any.whl" not in combined
    assert "conclave-0.1.2-py3-none-any.whl" not in combined
    assert "conclave-0.1.3-py3-none-any.whl" not in combined
    assert "conclave-0.1.4-py3-none-any.whl" not in combined
    assert "conclave-0.1.5-py3-none-any.whl" not in combined
    assert "conclave-0.1.16-py3-none-any.whl" not in combined
    assert "conclave-0.1.17-py3-none-any.whl" not in combined


def test_readme_describes_published_install_path():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "The published package is `conclave-personal`" in readme
    assert "Nach der PyPI-Veröffentlichung ist der Zielpfad" not in readme
    assert "Vor der PyPI-Veröffentlichung wird" not in readme
    assert "wird vor Veröffentlichung" not in readme
    assert "Lokale Artefakte können direkt aus einem frisch gebauten Wheel geprüft werden" not in readme
    assert ".venv-smoke/Scripts/pip install" not in readme


def test_public_readme_is_english_first():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "What Conclave Is For" in readme
    assert "Installation" in readme
    assert "Known Limitations" in readme
    assert "Wofür Conclave da ist" not in readme
    assert "Dokumentation" not in readme
    assert "Sicherheit" not in readme
