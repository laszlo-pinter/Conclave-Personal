"""Lizenzpruefung der Abhaengigkeiten des Board-Pakets (T1).

Liest die Abhaengigkeiten aus ``packages/board/pyproject.toml``, folgt ihnen
rekursiv durch die installierten Distributionen und prueft jede Lizenz gegen
eine Liste von Lizenzen, die mit Apache-2.0 vertraeglich sind. Unbekannte oder
fehlende Angaben lassen die Pruefung scheitern.

Ausdrueckliche Ausnahme: der PostgreSQL-Treiber ``psycopg2-binary`` (LGPL-3.0,
dynamisch genutzt, nur mit dem Extra ``postgres``).

Aufruf: python scripts/release/check_board_licenses.py [--extra postgres]
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOARD_PYPROJECT = ROOT / "packages" / "board" / "pyproject.toml"

# Mit Apache-2.0 vertraeglich (permissiv); Schreibweisen aus SPDX, License-Feld und Classifiern
ALLOWED = {
    "apache-2.0", "apache software license", "apache license 2.0", "apache 2.0", "apache license, version 2.0",
    "mit", "mit license", "mit-cmu", "mit-0",
    "bsd", "bsd license", "bsd-2-clause", "bsd-3-clause", "0bsd", "3-clause bsd license", "bsd 3-clause license",
    "isc", "isc license", "isc license (iscl)",
    "psf-2.0", "python software foundation license",
    "zpl-2.1", "zope public license",
    "unlicense", "the unlicense (unlicense)",
}

# Bewusste Ausnahmen mit Begruendung
EXCEPTIONS = {
    "psycopg2-binary": "LGPL-3.0: PostgreSQL-Treiber, dynamisch genutzt, nur mit dem Extra 'postgres' (T1)",
    "psycopg2": "LGPL-3.0: PostgreSQL-Treiber, dynamisch genutzt, nur mit dem Extra 'postgres' (T1)",
}

_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement(spec: str, extras: set[str]):
    """(Name, Extras) einer Anforderung, die in dieser Umgebung gilt; sonst None."""
    try:
        from packaging.requirements import Requirement
    except ImportError:                                   # frische venv: pip bringt packaging mit
        from pip._vendor.packaging.requirements import Requirement
    req = Requirement(spec)
    if req.marker is not None:
        environments = [{"extra": extra} for extra in (extras or {""})]
        if not any(req.marker.evaluate(env) for env in environments):
            return None
    return normalize(req.name), set(req.extras)


def board_requirements(extras: set[str]) -> list[str]:
    project = tomllib.loads(BOARD_PYPROJECT.read_text(encoding="utf-8"))["project"]
    specs = list(project.get("dependencies", []))
    for extra in extras:
        specs += project.get("optional-dependencies", {}).get(extra, [])
    return specs


def license_of(dist: metadata.Distribution) -> list[str]:
    """Lizenzangaben: License-Expression (PEP 639), sonst License-Feld, sonst Classifier."""
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return [part.strip().lower() for part in re.split(r"\s+(?:OR|AND|WITH)\s+|[()]", expression) if part.strip()]
    found = [c.split("::")[-1].strip().lower() for c in meta.get_all("Classifier") or []
             if c.startswith("License ::") and "OSI Approved" in c and c.count("::") >= 2]
    if found:
        return found
    text = (meta.get("License") or "").strip()
    if text and "\n" not in text and len(text) < 80:
        return [text.lower()]
    return []


def check(extras: set[str]) -> list[str]:
    problems, seen = [], set()
    todo = [(spec, extras) for spec in board_requirements(extras)]
    while todo:
        spec, active = todo.pop()
        parsed = _requirement(spec, active)
        if parsed is None:
            continue
        name, wanted = parsed
        if name in seen:
            continue
        seen.add(name)
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            problems.append(f"{name}: nicht installiert (erst das Board-Paket installieren)")
            continue
        licenses = license_of(dist)
        if name in EXCEPTIONS:
            print(f"Ausnahme  {name}: {EXCEPTIONS[name]}")
        elif not licenses:
            problems.append(f"{name}: keine Lizenzangabe")
        elif any(entry in ALLOWED for entry in licenses):
            print(f"ok        {name}: {', '.join(licenses)}")
        else:
            problems.append(f"{name}: {', '.join(licenses)} nicht auf der Liste")
        todo += [(req, wanted) for req in dist.requires or []]
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--extra", action="append", default=[], help="Extra des Board-Pakets, z. B. postgres")
    args = parser.parse_args(argv)
    problems = check(set(args.extra))
    for problem in problems:
        print(f"FEHLER    {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
