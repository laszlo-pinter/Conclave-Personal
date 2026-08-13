# Release Notes: v0.1.1

**Status:** Alpha-Patch-Release  
**Datum:** 2026-08-13

## Zweck

Conclave v0.1.1 ist ein kleiner Release-Patch für die öffentliche PyPI-Seite.
Der Anwendungsschnitt bleibt gegenüber v0.1.0 unverändert.

## Änderungen

- PyPI-Metadaten ergänzt: Author, Homepage, Source, Issues, Documentation und
  Changelog.
- Changelog-Link auf diese Release Notes aktualisiert.
- Release-Artefakt-Checks auf `conclave_personal-0.1.1` aktualisiert.
- Packaging-Tests ergänzt, damit Projektlinks und Autor nicht wieder fehlen.

## Installation

```bash
pipx install conclave-personal
conclave desktop
```

Vor der PyPI-Veröffentlichung kann das gebaute Wheel installiert werden:

```bash
python -m build --sdist --wheel
python -m venv .venv-smoke
.venv-smoke/Scripts/pip install dist/conclave_personal-0.1.1-py3-none-any.whl
.venv-smoke/Scripts/conclave --help
```

Unter Linux entsprechend mit `.venv-smoke/bin/...`.

## Verification

- `python -m pytest`
- `python -m build --sdist --wheel`
- Wheel-Metadaten enthalten `Author` und alle `Project-URL`-Einträge.

