"""T1: Board-Paket im Repo (packages/board): Version im Gleichschritt, Wheel-Pruefung, Lizenzpruefung."""

import importlib.util
import json
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BOARD = ROOT / "packages" / "board"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "release" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _version(pyproject: Path) -> str:
    return tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]


def test_board_and_personal_have_the_same_version():
    import conclave_board
    assert _version(BOARD / "pyproject.toml") == _version(ROOT / "pyproject.toml") == conclave_board.__version__


def test_board_dependencies_contain_no_provider_sdks():
    project = tomllib.loads((BOARD / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    names = " ".join(project["dependencies"]).lower()
    for sdk in ("anthropic", "openai", "httpx", "mcp"):
        assert sdk not in names
    assert project["scripts"] == {"conclave-board-server": "conclave_board.server:main"}


def test_personal_bundles_the_board_sources():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"conclave_board" = "packages/board/src/conclave_board"' in pyproject
    assert 'where = ["src", "packages/board/src"]' in pyproject


# ── Wheel-Pruefung (scripts/release/check_board_wheel.py) ───────────────────

check_board_wheel = _load("check_board_wheel")


def _wheel(tmp_path, version="1.2.3", extra=(), drop=()):
    dist = tmp_path / "dist"
    dist.mkdir()
    info = f"conclave_board-{version}.dist-info/"
    files = {
        "conclave_board/__init__.py": "", "conclave_board/server.py": "",
        **{name: "x" for name in check_board_wheel.REQUIRED_UI},
        f"{info}licenses/LICENSE": "Apache", f"{info}licenses/NOTICE": "x",
        f"{info}entry_points.txt": "[console_scripts]\nconclave-board-server = conclave_board.server:main\n",
        f"{info}METADATA": "Name: conclave-board\nLicense-Expression: Apache-2.0\nRequires-Dist: flask>=3.1\n",
    }
    files.update({name: "x" for name in extra})
    with zipfile.ZipFile(dist / f"conclave_board-{version}-py3-none-any.whl", "w") as zf:
        for name, content in files.items():
            if name not in drop:
                zf.writestr(name, content)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(f'[project]\nname = "conclave-personal"\nversion = "{version}"\n', encoding="utf-8")
    return dist, pyproject


def test_clean_board_wheel_passes(tmp_path):
    assert check_board_wheel.main([str(p) for p in _wheel(tmp_path)]) == 0


@pytest.mark.parametrize("bad", ["conclave_board/static/app.js", "conclave/__init__.py", "conclave_board/x.db",
                                 "conclave_board/workspace.py", "conclave_board/consultations.py",
                                 "conclave_board/providers/openai.py", "conclave_board/__pycache__/a.pyc"])
def test_board_wheel_with_foreign_files_fails(tmp_path, bad):
    assert check_board_wheel.main([str(p) for p in _wheel(tmp_path, extra=[bad])]) == 1


def test_board_wheel_with_the_board_page_passes(tmp_path):
    """U1: Seite und statische Dateien unter ui/ gehoeren ins Wheel."""
    extra = ["conclave_board/ui/static/board.css", "conclave_board/ui/static/vendor/fonts/fonts.css",
             "conclave_board/ui/static/vendor/licenses/marked-LICENSE.txt", "conclave_board/ui/__init__.py"]
    assert check_board_wheel.main([str(p) for p in _wheel(tmp_path, extra=extra)]) == 0


@pytest.mark.parametrize("bad", ["conclave_board/ui/other.html", "conclave_board/ui/notes.txt",
                                 "conclave_board/api/static/app.js", "conclave_board/templates/board.html",
                                 "conclave_board/ui/static/workspace.js"])
def test_board_wheel_with_resources_outside_the_page_fails(tmp_path, bad):
    assert check_board_wheel.main([str(p) for p in _wheel(tmp_path, extra=[bad])]) == 1


@pytest.mark.parametrize("missing", ["conclave_board/ui/board.html", "conclave_board/ui/static/board.js"])
def test_board_wheel_without_the_board_page_fails(tmp_path, missing):
    assert check_board_wheel.main([str(p) for p in _wheel(tmp_path, drop=[missing])]) == 1


def test_board_wheel_without_license_fails(tmp_path):
    dist, pyproject = _wheel(tmp_path, drop=["conclave_board-1.2.3.dist-info/licenses/NOTICE"])
    assert check_board_wheel.main([str(dist), str(pyproject)]) == 1


def test_board_wheel_with_another_version_fails(tmp_path):
    dist, _ = _wheel(tmp_path, version="1.2.2")
    other = tmp_path / "other.toml"
    other.write_text('[project]\nname = "conclave-personal"\nversion = "1.2.3"\n', encoding="utf-8")
    assert check_board_wheel.main([str(dist), str(other)]) == 1


# ── Lizenzpruefung (scripts/release/check_board_licenses.py) ────────────────

check_board_licenses = _load("check_board_licenses")


class _Dist:
    def __init__(self, **fields):
        self._fields = fields

    @property
    def metadata(self):
        fields = self._fields

        class Meta:
            def get(self, key, default=None):
                return fields.get(key, default)

            def get_all(self, key):
                return fields.get(key)
        return Meta()


@pytest.mark.parametrize("fields, expected", [
    ({"License-Expression": "Apache-2.0 OR BSD-3-Clause"}, ["apache-2.0", "bsd-3-clause"]),
    ({"Classifier": ["License :: OSI Approved :: MIT License"]}, ["mit license"]),
    ({"License": "BSD"}, ["bsd"]),
    ({}, []),
])
def test_license_is_read_from_metadata(fields, expected):
    assert check_board_licenses.license_of(_Dist(**fields)) == expected


def test_copyleft_is_not_on_the_list():
    for license in ("gpl-3.0", "agpl-3.0", "lgpl-3.0", "gnu general public license v3 (gplv3)"):
        assert license not in check_board_licenses.ALLOWED
    assert set(check_board_licenses.EXCEPTIONS) == {"psycopg2-binary", "psycopg2"}


def test_installed_board_dependencies_pass():
    """In der Testumgebung sind alle Abhaengigkeiten des Board-Pakets installiert."""
    assert check_board_licenses.check(set()) == []


# ── Selbsttest der API-Pruefung (scripts/release/board_api_breaking_variants.py) ──

def test_breaking_variants_each_change_the_v1_contract(tmp_path):
    variants = _load("board_api_breaking_variants")
    source = BOARD / "openapi" / "board-v1.json"
    assert variants.main([str(source), str(tmp_path)]) == 0
    original = json.loads(source.read_text(encoding="utf-8"))
    files = sorted(tmp_path.glob("*.json"))
    assert [f.stem for f in files] == sorted(variants.VARIANTS)
    for path in files:
        changed = json.loads(path.read_text(encoding="utf-8"))
        assert changed != original, path.name
    task_get = "/board/v1/projects/{slug}/tasks/{number}"
    removed = json.loads((tmp_path / "removed-response-field.json").read_text(encoding="utf-8"))
    schema = removed["paths"][task_get]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert "ref" not in schema["properties"] and "ref" not in schema["required"]
    required = json.loads((tmp_path / "new-required-request-field.json").read_text(encoding="utf-8"))
    body = required["paths"]["/board/v1/tasks"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert "priority" in body["required"]


def test_ci_script_runs_the_self_test_before_the_comparison():
    script = (ROOT / "scripts" / "release" / "check_board_api.sh").read_text(encoding="utf-8")
    assert script.index("board_api_breaking_variants.py") < script.index('git describe --tags')
    assert '"$WORK/oasdiff" breaking "$SPEC" "$SPEC" --fail-on ERR' in script
