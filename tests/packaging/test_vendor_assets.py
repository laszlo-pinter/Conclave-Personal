"""AP 4 / B5: Drittanbieter-Dateien werden lokal ausgeliefert und sind dokumentiert."""

import hashlib
import re
import tomllib
from pathlib import Path

from conclave.runtime.assets import get_asset_root


ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = get_asset_root()
VENDOR = ASSET_ROOT / "static" / "vendor"
THIRD_PARTY = ROOT / "THIRD_PARTY.md"

# Laden externer Ressourcen: src/href mit Schema, CSS-url()/@import mit Schema
EXTERNAL_RESOURCE = re.compile(
    r"""(?:\b(?:src|href)\s*=\s*["']?\s*(?:https?:)?//)|(?:url\(\s*["']?\s*(?:https?:)?//)|(?:@import\s+["']?(?:https?:)?//)""",
    re.I,
)


def _documented_checksums() -> dict[str, str]:
    text = THIRD_PARTY.read_text(encoding="utf-8")
    section = text.split("## Prüfsummen", 1)[1].split("\n## ", 1)[0]
    return dict(re.findall(r"^\| `([^`]+)` \| `([0-9a-f]{64})` \|$", section, re.M))


def _vendor_files() -> dict[str, Path]:
    return {p.relative_to(VENDOR).as_posix(): p for p in VENDOR.rglob("*") if p.is_file()}


def test_every_vendor_file_is_documented_with_matching_checksum():
    documented = _documented_checksums()
    files = _vendor_files()
    assert sorted(documented) == sorted(files)
    for name, path in files.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == documented[name], name


def test_vendor_licenses_are_shipped():
    licenses = {p.name for p in (VENDOR / "licenses").iterdir()}
    for expected in ("dompurify-LICENSE.txt", "marked-LICENSE.txt", "highlightjs-LICENSE.txt",
                     "swagger-ui-LICENSE.txt", "swagger-ui-NOTICE.txt",
                     "syne-OFL.txt", "syne-mono-OFL.txt", "dm-sans-OFL.txt"):
        assert expected in licenses


def test_ui_assets_load_no_external_resources():
    candidates = [ASSET_ROOT / "conclave-ui.html", *sorted((ASSET_ROOT / "static" / "css").glob("*.css")),
                  VENDOR / "fonts" / "fonts.css"]
    offenders = []
    for path in candidates:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if EXTERNAL_RESOURCE.search(line):
                offenders.append(f"{path.name}:{number}: {line.strip()[:120]}")
    assert offenders == []


def test_external_resource_pattern_detects_cdn_links():
    assert EXTERNAL_RESOURCE.search('<script src="https://cdnjs.cloudflare.com/x.js">')
    assert EXTERNAL_RESOURCE.search('<link href="//fonts.googleapis.com/css">')
    assert EXTERNAL_RESOURCE.search("@import url(https://fonts.googleapis.com/css);")
    assert not EXTERNAL_RESOURCE.search('<script src="static/vendor/marked.min.js">')
    assert not EXTERNAL_RESOURCE.search("url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'\")")


def test_ui_references_vendored_libraries():
    html = (ASSET_ROOT / "conclave-ui.html").read_text(encoding="utf-8")
    for ref in ("static/vendor/marked.min.js", "static/vendor/highlight/highlight.min.js",
                "static/vendor/purify.min.js", "static/vendor/highlight/github-dark.min.css",
                "static/vendor/fonts/fonts.css"):
        assert ref in html


def test_vendor_directories_are_packaged():
    package_data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"]["package-data"]["conclave"]
    for pattern in ("assets/static/vendor/*.js", "assets/static/vendor/fonts/*", "assets/static/vendor/highlight/*",
                    "assets/static/vendor/licenses/*", "assets/static/vendor/swagger-ui/*"):
        assert pattern in package_data


def test_vendor_files_are_kept_byte_exact_by_git():
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "src/conclave/assets/static/vendor/** -text" in attributes
