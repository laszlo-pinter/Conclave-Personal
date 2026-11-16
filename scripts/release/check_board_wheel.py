"""Prueft das Wheel des Board-Pakets (T1).

- genau ein Wheel ``conclave_board-<version>-py3-none-any.whl``; die Version ist
  dieselbe wie die von conclave-personal (Release im Gleichschritt)
- nur ``conclave_board/`` und die Metadaten, im Paket nur Python-Dateien
  (keine UI, kein ``static/``)
- keine Module fuer Provider, Workspace, Consultations oder Conversations
- LICENSE und NOTICE (Apache-2.0) in den Metadaten, Entry Point ``conclave-board``
- keine verbotenen Dateien (Datenbanken, Schluessel, Tokens, Logs, Caches)

Aufruf: python scripts/release/check_board_wheel.py [dist] [pyproject.toml]
"""

import sys
import tomllib
import zipfile
from pathlib import Path

FORBIDDEN_NAMES = ("anthropic", "openai", "universal", "provider", "workspace", "consultation", "conversation",
                   "orchestrat", "participant", "mcp", "static/", "assets/")
BANNED = (".db", ".key", ".token", ".pem", ".log", ".env", "__pycache__", ".pyc")


def problems(dist: Path, pyproject: Path) -> list[str]:
    version = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    expected = f"conclave_board-{version}-py3-none-any.whl"
    wheels = sorted(dist.glob("conclave_board-*.whl"))
    if [w.name for w in wheels] != [expected]:
        return [f"Wheel erwartet: {expected}, gefunden: {[w.name for w in wheels]}"]
    names = zipfile.ZipFile(wheels[0]).namelist()
    info = f"conclave_board-{version}.dist-info/"
    found = []
    outside = [n for n in names if not (n.startswith("conclave_board/") or n.startswith(info))]
    if outside:
        found.append(f"Dateien ausserhalb von conclave_board/: {outside[:20]}")
    not_python = [n for n in names if n.startswith("conclave_board/") and not n.endswith(".py")]
    if not_python:
        found.append(f"Nicht-Python-Dateien im Paket: {not_python[:20]}")
    forbidden = [n for n in names if n.startswith("conclave_board/")
                 and any(word in n.lower() for word in FORBIDDEN_NAMES)]
    if forbidden:
        found.append(f"Module, die nicht ins Board-Paket gehoeren: {forbidden}")
    bad = [n for n in names if any(part in n.lower() for part in BANNED)]
    if bad:
        found.append(f"Verbotene Dateien: {bad[:20]}")
    for required in ("conclave_board/__init__.py", "conclave_board/server.py", f"{info}licenses/LICENSE",
                     f"{info}licenses/NOTICE", f"{info}entry_points.txt"):
        if required not in names:
            found.append(f"Pflichtdatei fehlt: {required}")
    if f"{info}entry_points.txt" in names:
        entry_points = zipfile.ZipFile(wheels[0]).read(f"{info}entry_points.txt").decode("utf-8")
        if "conclave-board = conclave_board.server:main" not in entry_points:
            found.append("Entry Point conclave-board fehlt")
    if f"{info}METADATA" in names:
        metadata = zipfile.ZipFile(wheels[0]).read(f"{info}METADATA").decode("utf-8")
        if "License-Expression: Apache-2.0" not in metadata:
            found.append("METADATA nennt nicht License-Expression: Apache-2.0")
        if any(line.startswith("Requires-Dist: " + sdk) for line in metadata.splitlines()
               for sdk in ("anthropic", "openai", "httpx", "mcp")):
            found.append("METADATA verlangt ein Provider-SDK, httpx oder MCP")
    return found


def main(argv: list[str]) -> int:
    dist = Path(argv[0]) if argv else Path("dist")
    pyproject = Path(argv[1]) if len(argv) > 1 else Path("pyproject.toml")
    found = problems(dist, pyproject)
    for line in found:
        print(f"FEHLER: {line}", file=sys.stderr)
    if found:
        return 1
    print(f"Board-Wheel in {dist} geprueft.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
