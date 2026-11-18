"""Prueft die gebauten Pakete vor dem Release (CI und Publish, R14).

- genau ein Wheel und ein Sdist mit der Version aus pyproject.toml
- Pflichtdateien im Wheel (UI, OpenAPI, Vendor-Skripte, Entry Points)
- das mitgebuendelte Board-Paket mit seiner Lizenz (Apache-2.0, T1)
- keine verbotenen Dateien (Workspace, Datenbanken, Schluessel, Logs, Caches, interne Doku)

Aufruf: python scripts/release/check_dist.py [dist] [pyproject.toml]
"""

import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

REQUIRED_WHEEL = (
    "conclave/assets/conclave-ui.html",
    "conclave/assets/static/openapi.json",
    "conclave/assets/static/vendor/purify.min.js",
    "conclave/assets/static/vendor/marked.min.js",
    "conclave/assets/static/vendor/highlight/highlight.min.js",
    "conclave/assets/static/vendor/swagger-ui/swagger-ui-bundle.js",
    "conclave/assets/static/vendor/fonts/fonts.css",
    "conclave_board/__init__.py",
    "conclave_board/api/routes.py",
    "conclave_board/infrastructure/migrations.py",
    "conclave_board/ui/board.html",                 # Board-Seite aus dem Kern (U1)
    "conclave_board/ui/static/board.js",
    "conclave_reviewer/__init__.py",                 # Reviewer als eigenes Paket, mitgebuendelt (TR1)
    "conclave_reviewer/watch.py",
    "conclave_reviewer/reviewer-prompt-conclave.md",
    "conclave/reviewer/watch.py",                    # alter Name als Alias (TR1)
)
# Lizenzdateien in den Metadaten (relativ zu <name>-<version>.dist-info/licenses/)
REQUIRED_LICENSES = ("LICENSE", "packages/board/LICENSE", "packages/board/NOTICE")

BANNED = (
    "workspace/",
    ".db",
    ".db-wal",
    ".db-shm",
    ".key",
    ".token",
    ".pem",
    ".log",
    ".env",
    "__pycache__",
    "dsgvo",
    "docs/legal",
    "docs/betrieb",
    "sicherheit/",
)


def problems(dist: Path, pyproject: Path) -> list[str]:
    with open(pyproject, "rb") as handle:
        version = tomllib.load(handle)["project"]["version"]
    wheels, sdists = sorted(dist.glob("*.whl")), sorted(dist.glob("*.tar.gz"))
    found = []
    expected_wheel = f"conclave_personal-{version}-py3-none-any.whl"
    expected_sdist = f"conclave_personal-{version}.tar.gz"
    if [w.name for w in wheels] != [expected_wheel]:
        found.append(f"Wheel erwartet: {expected_wheel}, gefunden: {[w.name for w in wheels]}")
    if [s.name for s in sdists] != [expected_sdist]:
        found.append(f"Sdist erwartet: {expected_sdist}, gefunden: {[s.name for s in sdists]}")
    if found:
        return found

    wheel_names = set(zipfile.ZipFile(wheels[0]).namelist())
    entry_points = [n for n in wheel_names if n.endswith(".dist-info/entry_points.txt")]
    if len(entry_points) != 1:
        found.append(f"Unerwartete entry_points-Dateien: {entry_points}")
    info = f"conclave_personal-{version}.dist-info/licenses/"
    missing = sorted(set(REQUIRED_WHEEL) - wheel_names) + sorted(
        info + name for name in REQUIRED_LICENSES if info + name not in wheel_names)
    if missing:
        found.append(f"Im Wheel fehlen Pflichtdateien: {missing}")
    with tarfile.open(sdists[0]) as archive:
        sdist_names = archive.getnames()
    for kind, names in (("Wheel", wheel_names), ("Sdist", sdist_names)):
        bad = sorted(n for n in names if any(part in n.lower() for part in BANNED))
        if bad:
            found.append(f"{kind} enthaelt verbotene Dateien: {bad[:20]}")
    return found


def main(argv: list[str]) -> int:
    dist = Path(argv[0]) if argv else Path("dist")
    pyproject = Path(argv[1]) if len(argv) > 1 else Path("pyproject.toml")
    found = problems(dist, pyproject)
    for line in found:
        print(f"FEHLER: {line}", file=sys.stderr)
    if found:
        return 1
    print(f"Pakete in {dist} geprueft.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
