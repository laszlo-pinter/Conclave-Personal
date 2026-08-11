# Phase 13: Release-Vorbereitung

**Status:** abgeschlossen  
**Datum:** 2026-08-11  
**Branch:** `personal-multiplatform`

## Ziel

Das Projekt soll öffentlich verständlich, installierbar, wartbar und für
einen ersten Personal-Release prüfbar sein.

## Umgesetzt

- README um Release-relevante Einstiegspunkte ergänzt:
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
  - Judge-Agent zur Qualitätsprüfung verwenden
- Lizenz festgelegt:
  - PolyForm Noncommercial License 1.0.0
- Security-Hinweise für lokale API, Secrets, Workspace und Artefakte ergänzt.
- Release Notes für `v0.1.0` vorbereitet.
- Release-Checkliste aktualisiert.
- Packaging-Guards für Lizenz, Release-Doku und Screenshots ergänzt.

## Bewusst Noch Nicht Umgesetzt

- Keine signierten Artefakte.
- Kein Windows-Installer.
- Kein AppImage oder `.deb`.
- Keine automatisch erzeugten GIFs.
- Keine manuell bestätigten Smoke-Tests auf frischen Windows-/Linux-Systemen.

Diese Punkte bleiben als Release-Hardening vor einer breiteren
Veröffentlichung offen.

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

Phase 13 macht aus dem Umbau einen veröffentlichbaren Schnitt: nicht perfekt
ausinstalliert, aber erklärbar, lizenzierbar, testbar und mit klaren
bekannten Grenzen.
