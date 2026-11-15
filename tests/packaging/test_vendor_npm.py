"""R15 (conclave#50): Vendor-Dateien gegen die npm-Pakete (scripts/check_vendor.py).

Hier ohne Netz: Die Tarballs werden aus den ausgelieferten Dateien nachgebaut.
Der CI-Job ``vendor`` prueft gegen registry.npmjs.org.
"""

import importlib.util
import io
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("check_vendor", ROOT / "scripts" / "check_vendor.py")
check_vendor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_vendor)


def _tarballs(vendor, override=None):
    """Paket -> Tarball-Bytes mit den Dateien aus ``vendor`` (oder ``override``)."""
    override = override or {}
    members: dict[str, list[tuple[str, bytes]]] = {}
    for name, (package, member) in check_vendor.SOURCES.items():
        data = override.get(name, (vendor / name).read_bytes())
        members.setdefault(package, []).append((member, data))
    result = {}
    for package, files in members.items():
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as tf:
            for member, data in files:
                info = tarfile.TarInfo(member)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
        result[check_vendor.tarball_url(package)] = buffer.getvalue()
    return result


def _integrity(tarballs):
    by_url = {check_vendor.tarball_url(p): p for p, _ in check_vendor.SOURCES.values()}
    return {by_url[url]: check_vendor.integrity_of(data) for url, data in tarballs.items()}


def test_every_shipped_file_has_a_source():
    shipped = {p.relative_to(check_vendor.VENDOR).as_posix() for p in check_vendor.VENDOR.rglob("*") if p.is_file()}
    assert shipped == set(check_vendor.SOURCES) | check_vendor.OWN


def test_every_package_has_a_documented_integrity():
    packages = {package for package, _ in check_vendor.SOURCES.values()}
    assert packages <= set(check_vendor.documented_integrity())


def test_matching_files_and_integrity_pass():
    tarballs = _tarballs(check_vendor.VENDOR)
    assert check_vendor.problems(tarballs.__getitem__, integrity=_integrity(tarballs)) == []


def test_wrong_integrity_fails():
    tarballs = _tarballs(check_vendor.VENDOR)
    integrity = _integrity(tarballs)
    integrity["marked@15.0.7"] = check_vendor.integrity_of(b"anderes paket")
    found = check_vendor.problems(tarballs.__getitem__, integrity=integrity)
    assert found == ["marked@15.0.7: Integritaet stimmt nicht"]


@pytest.mark.parametrize("name", ["purify.min.js", "swagger-ui/swagger-ui-bundle.js"])
def test_modified_shipped_file_fails(name):
    """Die Datei im Tarball (und damit bei npm) weicht von der ausgelieferten ab."""
    tarballs = _tarballs(check_vendor.VENDOR, override={name: b"/* veraendert */"})
    found = check_vendor.problems(tarballs.__getitem__, integrity=_integrity(tarballs))
    assert len(found) == 1 and found[0].startswith(f"{name}: weicht von")


def test_unlisted_vendor_file_fails(tmp_path):
    import shutil
    vendor = tmp_path / "vendor"
    shutil.copytree(check_vendor.VENDOR, vendor)
    (vendor / "neu.min.js").write_text("x", encoding="utf-8")
    tarballs = _tarballs(vendor)
    found = check_vendor.problems(tarballs.__getitem__, vendor=vendor, integrity=_integrity(tarballs))
    assert found == ["neu.min.js: keine Quelle eingetragen"]
