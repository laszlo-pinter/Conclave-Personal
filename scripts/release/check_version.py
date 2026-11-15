"""Release nur ueber einen Tag v<Version>, und der Tag passt zu pyproject.toml (R14).

Aufruf: python scripts/release/check_version.py <github.ref> [pyproject.toml]
"""

import sys
import tomllib
from pathlib import Path

TAG_PREFIX = "refs/tags/v"


def problem(ref: str, pyproject: Path) -> str | None:
    """None, wenn veroeffentlicht werden darf; sonst der Grund."""
    if not ref.startswith(TAG_PREFIX):
        return f"Release nur ueber einen Tag v<Version>, nicht ueber '{ref}'."
    with open(pyproject, "rb") as handle:
        version = tomllib.load(handle)["project"]["version"]
    tag = ref[len(TAG_PREFIX):]
    if tag != version:
        return f"Tag v{tag} passt nicht zur Version {version} in {pyproject.name}."
    return None


def main(argv: list[str]) -> int:
    if not argv:
        print("Aufruf: check_version.py <github.ref> [pyproject.toml]", file=sys.stderr)
        return 2
    reason = problem(argv[0], Path(argv[1]) if len(argv) > 1 else Path("pyproject.toml"))
    if reason:
        print(f"FEHLER: {reason}", file=sys.stderr)
        return 1
    print(f"Tag und Version passen: {argv[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
