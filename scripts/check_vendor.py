"""Prueft die ausgelieferten Drittanbieter-Dateien gegen die npm-Pakete (R15).

Fuer jedes Paket aus THIRD_PARTY.md: Tarball von registry.npmjs.org laden, gegen
die dokumentierte Integritaet (sha512) pruefen und jede ausgelieferte Datei
Byte fuer Byte mit der Datei im Tarball vergleichen. Braucht Netz (CI-Job).

Aufruf: python scripts/check_vendor.py
"""

from __future__ import annotations

import base64
import hashlib
import io
import re
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "src" / "conclave" / "assets" / "static" / "vendor"
THIRD_PARTY = ROOT / "THIRD_PARTY.md"
REGISTRY = "https://registry.npmjs.org"

# Ausgelieferte Datei -> (Paket@Version, Pfad im Tarball)
SOURCES = {
    "purify.min.js": ("dompurify@3.4.17", "package/dist/purify.min.js"),
    "licenses/dompurify-LICENSE.txt": ("dompurify@3.4.17", "package/LICENSE"),
    "marked.min.js": ("marked@15.0.7", "package/marked.min.js"),
    "licenses/marked-LICENSE.txt": ("marked@15.0.7", "package/LICENSE.md"),
    "highlight/highlight.min.js": ("@highlightjs/cdn-assets@11.11.1", "package/highlight.min.js"),
    "highlight/github-dark.min.css": ("@highlightjs/cdn-assets@11.11.1", "package/styles/github-dark.min.css"),
    "licenses/highlightjs-LICENSE.txt": ("@highlightjs/cdn-assets@11.11.1", "package/LICENSE"),
    "swagger-ui/swagger-ui-bundle.js": ("swagger-ui-dist@5.33.2", "package/swagger-ui-bundle.js"),
    "swagger-ui/swagger-ui.css": ("swagger-ui-dist@5.33.2", "package/swagger-ui.css"),
    "licenses/swagger-ui-LICENSE.txt": ("swagger-ui-dist@5.33.2", "package/LICENSE"),
    "licenses/swagger-ui-NOTICE.txt": ("swagger-ui-dist@5.33.2", "package/NOTICE"),
    "fonts/syne-latin-400-normal.woff2": ("@fontsource/syne@5.3.0", "package/files/syne-latin-400-normal.woff2"),
    "fonts/syne-latin-600-normal.woff2": ("@fontsource/syne@5.3.0", "package/files/syne-latin-600-normal.woff2"),
    "fonts/syne-latin-700-normal.woff2": ("@fontsource/syne@5.3.0", "package/files/syne-latin-700-normal.woff2"),
    "fonts/syne-latin-800-normal.woff2": ("@fontsource/syne@5.3.0", "package/files/syne-latin-800-normal.woff2"),
    "licenses/syne-OFL.txt": ("@fontsource/syne@5.3.0", "package/LICENSE"),
    "fonts/syne-mono-latin-400-normal.woff2": ("@fontsource/syne-mono@5.3.0",
                                               "package/files/syne-mono-latin-400-normal.woff2"),
    "licenses/syne-mono-OFL.txt": ("@fontsource/syne-mono@5.3.0", "package/LICENSE"),
    "fonts/dm-sans-latin-300-italic.woff2": ("@fontsource/dm-sans@5.3.0", "package/files/dm-sans-latin-300-italic.woff2"),
    "fonts/dm-sans-latin-300-normal.woff2": ("@fontsource/dm-sans@5.3.0", "package/files/dm-sans-latin-300-normal.woff2"),
    "fonts/dm-sans-latin-400-normal.woff2": ("@fontsource/dm-sans@5.3.0", "package/files/dm-sans-latin-400-normal.woff2"),
    "fonts/dm-sans-latin-500-normal.woff2": ("@fontsource/dm-sans@5.3.0", "package/files/dm-sans-latin-500-normal.woff2"),
    "licenses/dm-sans-OFL.txt": ("@fontsource/dm-sans@5.3.0", "package/LICENSE"),
}

# Eigener Code, nicht aus npm
OWN = {"fonts/fonts.css"}

# Board-Seite im Board-Kern (U1): marked, DOMPurify und die Schriften, dieselben Versionen
KERN_VENDOR = ROOT / "packages" / "board" / "src" / "conclave_board" / "ui" / "static" / "vendor"
KERN_SOURCES = {name: source for name, source in SOURCES.items()
                if name.startswith(("fonts/", "licenses/dompurify", "licenses/marked", "licenses/syne", "licenses/dm-sans"))
                or name in ("purify.min.js", "marked.min.js")}


def documented_integrity(text: str | None = None) -> dict[str, str]:
    """Paket@Version -> sha512-Integritaet aus THIRD_PARTY.md."""
    text = text if text is not None else THIRD_PARTY.read_text(encoding="utf-8")
    section = text.split("## npm-Integrität der Pakete", 1)[1].split("\n## ", 1)[0]
    return dict(re.findall(r"^\| `([^`]+)` \| `(sha512-[A-Za-z0-9+/=]+)` \|$", section, re.M))


def tarball_url(package: str) -> str:
    name, version = package.rsplit("@", 1)
    return f"{REGISTRY}/{name}/-/{name.split('/')[-1]}-{version}.tgz"


def integrity_of(data: bytes) -> str:
    return "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode()


def problems(fetch, vendor: Path = VENDOR, integrity: dict[str, str] | None = None,
             sources: dict[str, tuple[str, str]] | None = None, own: set[str] | None = None) -> list[str]:
    """Abweichungen; ``fetch(url) -> bytes`` laedt einen Tarball."""
    integrity = integrity if integrity is not None else documented_integrity()
    sources = SOURCES if sources is None else sources
    own = OWN if own is None else own
    found = []
    shipped = {p.relative_to(vendor).as_posix() for p in vendor.rglob("*") if p.is_file()}
    for name in sorted(shipped - set(sources) - own):
        found.append(f"{name}: keine Quelle eingetragen")
    tarballs: dict[str, tarfile.TarFile | None] = {}
    for name, (package, member) in sorted(sources.items()):
        if name not in shipped:
            found.append(f"{name}: eingetragen, aber nicht ausgeliefert")
            continue
        if package not in tarballs:
            expected = integrity.get(package)
            data = fetch(tarball_url(package))
            if expected is None:
                found.append(f"{package}: keine Integritaet in THIRD_PARTY.md")
                tarballs[package] = None
            elif integrity_of(data) != expected:
                found.append(f"{package}: Integritaet stimmt nicht")
                tarballs[package] = None
            else:
                tarballs[package] = tarfile.open(fileobj=io.BytesIO(data))
        archive = tarballs[package]
        if archive is None:
            continue
        try:
            original = archive.extractfile(member).read()
        except (KeyError, AttributeError):
            found.append(f"{name}: {member} fehlt in {package}")
            continue
        if (vendor / name).read_bytes() != original:
            found.append(f"{name}: weicht von {package} ab")
    return found


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:  # nosec B310 - feste https-URL der npm-Registry
        return response.read()


def main() -> int:
    found = problems(_fetch)
    found += [f"Kern: {line}" for line in problems(_fetch, KERN_VENDOR, sources=KERN_SOURCES, own=OWN)]
    for line in found:
        print(f"FEHLER: {line}", file=sys.stderr)
    if found:
        return 1
    print(f"{len(SOURCES) + len(KERN_SOURCES)} Dateien stimmen mit den npm-Paketen ueberein.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
