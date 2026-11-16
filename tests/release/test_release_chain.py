"""R14 (conclave#49): Release-Kette.

- Release ohne Tag scheitert; Tag und Version muessen passen.
- Ein Paket mit verbotener Datei scheitert.
- publish.yml: CI (Tests Linux/Windows, UI, Security, Postgres) und Paketpruefung
  sind Voraussetzung; Build-Werkzeuge mit Hashes; kein pip-Cache; keine
  gespeicherten Git-Zugangsdaten.
"""

import importlib.util
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "release" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_version = _load("check_version")
check_dist = _load("check_dist")


def _pyproject(tmp_path, version="1.2.3"):
    path = tmp_path / "pyproject.toml"
    path.write_text(f'[project]\nname = "conclave-personal"\nversion = "{version}"\n', encoding="utf-8")
    return path


# ── Tag und Version ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("ref", ["refs/heads/main", "refs/heads/v1.2.3", "refs/tags/1.2.3", ""])
def test_release_without_a_tag_fails(tmp_path, ref):
    assert check_version.main([ref, str(_pyproject(tmp_path))]) == 1


def test_tag_and_version_must_match(tmp_path):
    assert check_version.main(["refs/tags/v1.2.4", str(_pyproject(tmp_path))]) == 1
    assert check_version.main(["refs/tags/v1.2.3", str(_pyproject(tmp_path))]) == 0


# ── Paketpruefung ───────────────────────────────────────────────────────────

def _dist(tmp_path, version="1.2.3", extra=(), sdist_extra=()):
    dist = tmp_path / "dist"
    dist.mkdir()
    with zipfile.ZipFile(dist / f"conclave_personal-{version}-py3-none-any.whl", "w") as zf:
        for name in (*check_dist.REQUIRED_WHEEL, f"conclave_personal-{version}.dist-info/entry_points.txt",
                     "conclave/__init__.py", *extra):
            zf.writestr(name, "x")
    with tarfile.open(dist / f"conclave_personal-{version}.tar.gz", "w:gz") as tf:
        for name in (f"conclave_personal-{version}/pyproject.toml", f"conclave_personal-{version}/src/conclave/__init__.py",
                     *(f"conclave_personal-{version}/{n}" for n in sdist_extra)):
            info = tarfile.TarInfo(name)
            info.size = 1
            tf.addfile(info, io.BytesIO(b"x"))
    return dist


def test_clean_package_passes(tmp_path):
    assert check_dist.main([str(_dist(tmp_path)), str(_pyproject(tmp_path))]) == 0


BANNED_EXAMPLES = ["conclave/secret.key", "conclave/api.token", "workspace/notiz.md", "conclave/conclave.db",
                   "conclave/__pycache__/x.pyc", "docs/betrieb/x.md", ".env", "conclave/.env",
                   "sicherheit/analyse.md"]


@pytest.mark.parametrize("bad", BANNED_EXAMPLES)
def test_package_with_a_banned_file_fails(tmp_path, bad):
    assert check_dist.main([str(_dist(tmp_path, extra=[bad])), str(_pyproject(tmp_path))]) == 1


@pytest.mark.parametrize("bad", BANNED_EXAMPLES)
def test_sdist_with_a_banned_file_fails(tmp_path, bad):
    """R14-Review V1: Das Sdist ist der Weg, auf dem Repo-Dateien durchrutschen koennten."""
    assert check_dist.main([str(_dist(tmp_path, sdist_extra=[bad])), str(_pyproject(tmp_path))]) == 1


def test_package_with_another_version_fails(tmp_path):
    assert check_dist.main([str(_dist(tmp_path, version="1.2.2")), str(_pyproject(tmp_path))]) == 1


# ── Workflows ───────────────────────────────────────────────────────────────

yaml = pytest.importorskip("yaml")


def _workflow(name):
    data = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    data["on"] = data.pop(True, data.get("on"))           # YAML 1.1: "on" wird zu True
    return data


def _steps(workflow):
    for job_name, job in workflow["jobs"].items():
        for step in job.get("steps", []):
            yield job_name, step


def test_publish_requires_a_tag_and_all_checks():
    jobs = _workflow("publish.yml")["jobs"]
    publish = jobs["publish"]
    assert "startsWith(github.ref, 'refs/tags/v')" in publish["if"]
    needed = set(publish["needs"])
    assert {"version", "ci", "build"} <= needed
    assert jobs["ci"]["uses"] == "./.github/workflows/ci.yml"
    assert jobs["ci"]["with"]["release"] is True
    assert "check_version.py" in str(jobs["version"]["steps"])
    assert "check_dist.py" in str(jobs["build"]["steps"])
    assert set(jobs["build"]["needs"]) >= {"version", "ci"}


def test_ci_covers_what_the_release_needs():
    ci = _workflow("ci.yml")
    assert "workflow_call" in ci["on"]
    jobs = ci["jobs"]
    assert {"test", "ui-browser", "security", "postgres", "vendor", "build"} <= set(jobs)
    assert "check_vendor.py" in str(jobs["vendor"]["steps"])
    assert "windows-latest" in jobs["test"]["strategy"]["matrix"]["os"]
    assert "check_dist.py" in str(jobs["build"]["steps"])


@pytest.mark.parametrize("name", ["ci.yml", "publish.yml"])
def test_checkouts_do_not_keep_credentials(name):
    for job, step in _steps(_workflow(name)):
        if str(step.get("uses", "")).startswith("actions/checkout@"):
            assert step.get("with", {}).get("persist-credentials") is False, job


def test_release_jobs_use_no_pip_cache_and_pinned_tools():
    for job, step in _steps(_workflow("publish.yml")):
        if str(step.get("uses", "")).startswith("actions/setup-python@"):
            assert "cache" not in step.get("with", {}), job
    build = str(_workflow("publish.yml")["jobs"]["build"]["steps"])
    assert "--require-hashes" in build and "requirements/release-tools.txt" in build and "--no-isolation" in build
    assert "--upgrade pip" not in build
    # Im Release-Lauf auch die CI ohne Cache
    ci_text = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    assert "cache: pip" not in ci_text and "inputs.release" in ci_text


def test_release_tools_are_all_hashed():
    lines = [line for line in (ROOT / "requirements" / "release-tools.txt").read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.startswith("#")]
    assert lines and all("==" in line and "--hash=sha256:" in line for line in lines)
    names = {line.split("==")[0] for line in lines}
    assert {"pip", "build", "setuptools", "wheel"} <= names
