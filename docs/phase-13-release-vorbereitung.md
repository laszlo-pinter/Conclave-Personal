# Phase 13: Release-Vorbereitung

**Status:** abgeschlossen  
**Datum:** 2026-08-11  
**Branch:** `personal-multiplatform`

## Ziel

Das Projekt soll oeffentlich verstaendlich, installierbar, wartbar und fuer
einen ersten Personal-Release pruefbar sein.

## Umgesetzt

- README um Release-relevante Einstiegspunkte ergaenzt:
  - Windows Quickstart
  - Linux Quickstart
  - Provider
  - Workspace
  - Auto-Loop und Judge
  - Migration
  - Security
- Release-Screenshots erzeugt:
  - `docs/assets/screenshots/conclave-studio-desktop.png`
  - `docs/assets/screenshots/conclave-agents-desktop.png`
- Beispiel-Workflows dokumentiert:
  - Text von drei Agenten reviewen lassen
  - Architekturentscheidung diskutieren
  - Datei im Workspace als Kontext nutzen
  - Judge-Agent zur Qualitaetspruefung verwenden
- Lizenz festgelegt:
  - PolyForm Noncommercial License 1.0.0
- Security-Hinweise fuer lokale API, Secrets, Workspace und Artefakte ergaenzt.
- Release Notes fuer `v0.1.0` vorbereitet.
- Release-Checkliste aktualisiert.
- Packaging-Guards fuer Lizenz, Release-Doku und Screenshots ergaenzt.

## Bewusst Noch Nicht Umgesetzt

- Keine signierten Artefakte.
- Kein Windows-Installer.
- Kein AppImage oder `.deb`.
- Keine automatisch erzeugten GIFs.
- Keine manuell bestaetigten Smoke-Tests auf frischen Windows-/Linux-Systemen.

Diese Punkte bleiben als Release-Hardening vor einer breiteren
Veroeffentlichung offen.

## Tests

Neue/erweiterte Tests:

- `tests/packaging/test_release_readiness.py`
- `tests/packaging/test_distribution_config.py`

Fokussierter Lauf:

```powershell
python -m pytest tests\packaging\test_distribution_config.py tests\packaging\test_release_readiness.py
```

Verifikation am 2026-08-11:

- fokussierter Packaging-/Release-Lauf
  - `9 passed`
- kompletter Testlauf
  - `783 passed, 1 skipped`
- `python -m build --sdist --wheel`
  - erfolgreich
- lokaler Artefakt-Check
  - `LICENSE` im sdist
  - Lizenzdatei im Wheel
  - Release-Doku und Screenshots im sdist
  - keine Workspace-, DB-, Key-, Log-, Cache- oder DSGVO-/Legal-Altpfade

## Einordnung

Phase 13 macht aus dem Umbau einen veroeffentlichbaren Schnitt: nicht perfekt
ausinstalliert, aber erklaerbar, lizenzierbar, testbar und mit klaren
bekannten Grenzen.
