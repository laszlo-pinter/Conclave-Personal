"""TR1 (conclave#123): Reviewer als eigenes Paket (packages/reviewer).

Version im Gleichschritt, nur der Board-Kern als Abhaengigkeit, Personal buendelt es, alte Namen als
Aliase, Standardorte wie in Personal ohne Import aus Personal, Importgrenze und Wheel-Pruefung.
"""

import ast
import importlib
import importlib.util
import os
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REVIEWER = ROOT / "packages" / "reviewer"
SOURCE = REVIEWER / "src" / "conclave_reviewer"
MODULES = sorted(p.stem for p in SOURCE.glob("*.py") if p.stem not in ("__init__", "__main__"))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "release" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _project(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))["project"]


def test_reviewer_and_personal_have_the_same_version():
    assert _project(REVIEWER / "pyproject.toml")["version"] == _project(ROOT / "pyproject.toml")["version"]


def test_reviewer_needs_only_the_board_core_and_keeps_its_command():
    project = _project(REVIEWER / "pyproject.toml")
    assert project["dependencies"] == ["conclave-board>=0.8,<0.9"]
    assert project["scripts"] == {"conclave-reviewer": "conclave_reviewer.cli:main"}
    assert project["license"] == "LicenseRef-PolyForm-Noncommercial-1.0.0"
    assert (REVIEWER / "LICENSE").read_text(encoding="utf-8") == (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "separate license" in (REVIEWER / "README.md").read_text(encoding="utf-8")


def test_personal_bundles_the_reviewer_and_starts_the_new_module():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["tool"]["setuptools"]["package-dir"]["conclave_reviewer"] == "packages/reviewer/src/conclave_reviewer"
    assert "packages/reviewer/src" in pyproject["tool"]["setuptools"]["packages"]["find"]["where"]
    assert pyproject["tool"]["setuptools"]["package-data"]["conclave_reviewer"] == ["reviewer-prompt-conclave.md"]
    assert pyproject["project"]["scripts"]["conclave-reviewer"] == "conclave_reviewer.cli:main"
    launch = (ROOT / "src" / "conclave" / "runtime" / "reviewer_launch.py").read_text(encoding="utf-8")
    assert '"-m", "conclave_reviewer", "run"' in launch


@pytest.mark.parametrize("module", MODULES)
def test_old_module_names_are_aliases_of_the_same_modules(module):
    """monkeypatch auf conclave.reviewer.<modul> wirkt im Paket (wie die Aliase aus T1)."""
    old = importlib.import_module(f"conclave.reviewer.{module}")
    assert old is importlib.import_module(f"conclave_reviewer.{module}")


@pytest.mark.parametrize("module", ["conclave_reviewer", "conclave.reviewer"])
def test_both_module_names_start_the_cli(module):
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(
        str(ROOT / part) for part in ("src", "packages/board/src", "packages/reviewer/src")))
    result = subprocess.run([sys.executable, "-m", module, "--help"], capture_output=True, text=True, env=env,
                            timeout=60)
    assert result.returncode == 0 and "import-config" in result.stdout, result.stderr


@pytest.mark.parametrize("platform,env,expected", [
    ("win32", {"APPDATA": r"C:\Users\x\AppData\Roaming"}, r"C:\Users\x\AppData\Roaming\Conclave"),
    ("win32", {"USERPROFILE": r"C:\Users\y"}, r"C:\Users\y\AppData\Roaming\Conclave"),
    ("linux", {"XDG_CONFIG_HOME": "/srv/cfg"}, "/srv/cfg/conclave"),
    ("linux", {}, None),
])
def test_default_config_dir_follows_the_rule_of_personal(platform, env, expected):
    from conclave.runtime.paths import get_runtime_paths
    from conclave_reviewer.paths import conclave_config_dir

    home = Path("/home/z")
    system = "windows" if platform == "win32" else "linux"
    if platform == "win32" and "USERPROFILE" in env:
        ours, theirs = conclave_config_dir(env, platform), get_runtime_paths(system, env).config_dir
    else:
        ours, theirs = conclave_config_dir(env, platform, home), get_runtime_paths(system, env, home).config_dir
    assert ours == theirs
    if expected and (platform == "win32") == (os.name == "nt"):     # Pfadtext nur auf passendem System
        assert str(ours) == str(Path(expected))


def _imports(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_reviewer_source_imports_nothing_from_personal_or_the_team_package():
    found = {f"{p.name}: {name}" for p in SOURCE.glob("*.py") for name in _imports(p)
             if name == "conclave" or name.startswith(("conclave.", "conclave_board_team"))
             or name.startswith(("conclave_board.application", "conclave_board.api", "conclave_board.infrastructure"))}
    assert found == set()


# ── Wheel-Pruefung (scripts/release/check_reviewer_wheel.py) ────────────────

check_reviewer_wheel = _load("check_reviewer_wheel")


def _wheel(tmp_path, version="1.2.3", extra=None, drop=(), license_text="PolyForm Noncommercial License 1.0.0",
           requires=("conclave-board<0.9,>=0.8",), entry="conclave-reviewer = conclave_reviewer.cli:main"):
    dist = tmp_path / "dist"
    dist.mkdir()
    info = f"conclave_reviewer-{version}.dist-info/"
    files = {name: "x" for name in check_reviewer_wheel.REQUIRED}
    files.update({
        f"{info}licenses/LICENSE": license_text,
        f"{info}entry_points.txt": f"[console_scripts]\n{entry}\n",
        f"{info}METADATA": "Name: conclave-reviewer\nLicense-Expression: LicenseRef-PolyForm-Noncommercial-1.0.0\n"
                          + "".join(f"Requires-Dist: {r}\n" for r in requires),
    })
    files.update(extra or {})
    with zipfile.ZipFile(dist / f"conclave_reviewer-{version}-py3-none-any.whl", "w") as zf:
        for name, content in files.items():
            if name not in drop:
                zf.writestr(name, content)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(f'[project]\nname = "conclave-personal"\nversion = "{version}"\n', encoding="utf-8")
    return dist, pyproject


def test_clean_reviewer_wheel_passes(tmp_path):
    assert check_reviewer_wheel.main([str(p) for p in _wheel(tmp_path)]) == 0


@pytest.mark.parametrize("bad", ["conclave/__init__.py", "conclave/reviewer/watch.py", "conclave_board/server.py",
                                 "conclave_board_team/app.py", "conclave_reviewer/static/app.js",
                                 "conclave_reviewer/state.db", "conclave_reviewer/__pycache__/a.pyc"])
def test_reviewer_wheel_with_foreign_files_fails(tmp_path, bad):
    assert check_reviewer_wheel.main([str(p) for p in _wheel(tmp_path, extra={bad: "x"})]) == 1


@pytest.mark.parametrize("variant", [
    {"license_text": "Apache License"},
    {"requires": ("conclave-board<0.9,>=0.8", "httpx>=0.27")},
    {"requires": ("conclave-board<0.9,>=0.8", "conclave-personal")},
    {"entry": "conclave-reviewer = conclave.reviewer.cli:main"},
    {"drop": ("conclave_reviewer/reviewer-prompt-conclave.md",)},
    {"version": "0.0.1"},
])
def test_reviewer_wheel_with_wrong_metadata_fails(tmp_path, variant):
    dist, pyproject = _wheel(tmp_path, **variant)
    if "version" in variant:
        pyproject.write_text('[project]\nname = "conclave-personal"\nversion = "9.9.9"\n', encoding="utf-8")
    assert check_reviewer_wheel.main([str(dist), str(pyproject)]) == 1
