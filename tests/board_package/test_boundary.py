"""T1: Grenze des Board-Pakets.

- ``conclave_board`` importiert nichts aus ``conclave`` (auch nicht in Funktionen).
- Jede Datei traegt den Apache-2.0-Kopf.
- Im Paket liegen nur Python-Dateien, keine UI und keine Module fuer Provider,
  Workspace, Consultations oder Conversations.

Dieselbe Grenze prueft ``lint-imports`` (Vertrag in pyproject.toml) in der CI.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOARD = ROOT / "packages" / "board" / "src" / "conclave_board"
HEADER = "# SPDX-License-Identifier: Apache-2.0\n# Copyright 2026 Laszlo Pinter\n"
FORBIDDEN_NAMES = ("anthropic", "openai", "universal", "provider", "workspace", "consultation", "conversation",
                   "orchestrat", "participant", "message", "mcp")


def _files():
    files = sorted(BOARD.rglob("*.py"))
    assert files, BOARD
    return files


def _imports(path: Path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module


def test_board_package_does_not_import_conclave():
    offending = [(p.relative_to(BOARD).as_posix(), name) for p in _files() for name in _imports(p)
                 if name == "conclave" or name.startswith("conclave.")]
    assert offending == []


def test_core_and_personal_do_not_import_the_team_package():
    """Plan 2.3: Das Team-Paket haengt vom Kern ab, nie umgekehrt; Personal kennt es nicht."""
    personal = ROOT / "src" / "conclave"
    offending = [(p.relative_to(ROOT).as_posix(), name) for p in [*_files(), *sorted(personal.rglob("*.py"))]
                 for name in _imports(p) if name.split(".")[0] == "conclave_board_team"]
    assert offending == []


def test_board_package_does_not_import_provider_sdks():
    offending = [(p.relative_to(BOARD).as_posix(), name) for p in _files() for name in _imports(p)
                 if name.split(".")[0] in ("anthropic", "openai", "httpx", "mcp")]
    assert offending == []


def test_every_board_file_has_the_apache_header():
    missing = [p.relative_to(BOARD).as_posix() for p in _files()
               if not p.read_text(encoding="utf-8").startswith(HEADER)]
    assert missing == []


def test_board_package_contains_only_board_modules():
    others = [p.relative_to(BOARD).as_posix() for p in BOARD.rglob("*")
              if p.is_file() and p.suffix != ".py" and "__pycache__" not in p.parts]
    assert others == []                                       # keine static/, keine UI-Dateien
    names = [p.relative_to(BOARD).as_posix() for p in _files()]
    assert [n for n in names if any(word in n.lower() for word in FORBIDDEN_NAMES)] == []


def test_personal_aliases_point_to_the_same_modules():
    """Die alten Modulnamen in Personal sind Aliase, kein zweiter Stand."""
    import conclave.application.board as old_service
    import conclave.domain.board as old_domain
    import conclave.runtime.file_security as old_security
    import conclave_board.application.board as service
    import conclave_board.domain.board as domain
    import conclave_board.runtime.file_security as security

    assert old_service is service and old_domain is domain and old_security is security
