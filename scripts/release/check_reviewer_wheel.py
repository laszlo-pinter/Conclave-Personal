"""Prueft das Wheel des Reviewer-Pakets (TR1).

- genau ein Wheel ``conclave_reviewer-<version>-py3-none-any.whl``; die Version ist dieselbe wie die
  von conclave-personal (Release im Gleichschritt)
- nur ``conclave_reviewer/`` und die Metadaten: kein Code aus Personal (``conclave/``), kein Board-Kern
  und kein Team-Paket; ausser Python nur der mitgelieferte Prompt
- LICENSE (PolyForm Noncommercial) in den Metadaten, Entry Point ``conclave-reviewer``
- als Abhaengigkeit nur der Board-Kern, keine Provider-SDKs, kein httpx, kein MCP, kein Flask
- keine verbotenen Dateien (Datenbanken, Schluessel, Tokens, Logs, Caches)

Aufruf: python scripts/release/check_reviewer_wheel.py [dist] [pyproject.toml]
"""

import sys
import tomllib
import zipfile
from pathlib import Path

PACKAGE = "conclave_reviewer/"
RESOURCES = (PACKAGE + "reviewer-prompt-conclave.md",)
REQUIRED = (PACKAGE + "__init__.py", PACKAGE + "cli.py", PACKAGE + "watch.py", PACKAGE + "git_mcp.py",
            PACKAGE + "paths.py", *RESOURCES)
BANNED = (".db", ".key", ".token", ".pem", ".log", ".env", "__pycache__", ".pyc")
ALLOWED_REQUIRES = ("conclave-board",)


def problems(dist: Path, pyproject: Path) -> list[str]:
    version = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    expected = f"conclave_reviewer-{version}-py3-none-any.whl"
    wheels = sorted(dist.glob("conclave_reviewer-*.whl"))
    if [w.name for w in wheels] != [expected]:
        return [f"Wheel erwartet: {expected}, gefunden: {[w.name for w in wheels]}"]
    wheel = zipfile.ZipFile(wheels[0])
    names = wheel.namelist()
    info = f"conclave_reviewer-{version}.dist-info/"
    found = []
    outside = [n for n in names if not (n.startswith(PACKAGE) or n.startswith(info))]
    if outside:
        found.append(f"Dateien ausserhalb von conclave_reviewer/ (z. B. Personal, Kern): {outside[:20]}")
    not_python = [n for n in names if n.startswith(PACKAGE) and not n.endswith(".py") and n not in RESOURCES]
    if not_python:
        found.append(f"Nicht-Python-Dateien im Paket: {not_python[:20]}")
    bad = [n for n in names if any(part in n.lower() for part in BANNED)]
    if bad:
        found.append(f"Verbotene Dateien: {bad[:20]}")
    for required in (*REQUIRED, f"{info}licenses/LICENSE", f"{info}entry_points.txt", f"{info}METADATA"):
        if required not in names:
            found.append(f"Pflichtdatei fehlt: {required}")
    if f"{info}licenses/LICENSE" in names and \
            "PolyForm Noncommercial" not in wheel.read(f"{info}licenses/LICENSE").decode("utf-8"):
        found.append("LICENSE ist nicht PolyForm Noncommercial")
    if f"{info}entry_points.txt" in names:
        entry_points = wheel.read(f"{info}entry_points.txt").decode("utf-8")
        if "conclave-reviewer = conclave_reviewer.cli:main" not in entry_points:
            found.append("Entry Point conclave-reviewer fehlt")
    if f"{info}METADATA" in names:
        metadata = wheel.read(f"{info}METADATA").decode("utf-8")
        if "License-Expression: LicenseRef-PolyForm-Noncommercial-1.0.0" not in metadata:
            found.append("METADATA nennt nicht License-Expression: LicenseRef-PolyForm-Noncommercial-1.0.0")
        requires = [line.split(":", 1)[1].strip() for line in metadata.splitlines()
                    if line.startswith("Requires-Dist:")]
        foreign = [r for r in requires if not r.lower().startswith(ALLOWED_REQUIRES)]
        if foreign:
            found.append(f"METADATA verlangt mehr als den Board-Kern: {foreign}")
    return found


def main(argv: list[str]) -> int:
    dist = Path(argv[0]) if argv else Path("dist")
    pyproject = Path(argv[1]) if len(argv) > 1 else Path("pyproject.toml")
    found = problems(dist, pyproject)
    for line in found:
        print(f"FEHLER: {line}", file=sys.stderr)
    if found:
        return 1
    print(f"Reviewer-Wheel in {dist} geprueft.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
