# Workspace-Bereinigungsplan

**Datum:** 2026-08-11  
**Ziel:** Das Worktree auf den Personal-Release-Schnitt reduzieren, ohne
laufzeitrelevante Dateien, neue Release-Doku oder lokale Nutzerdaten
versehentlich zu verlieren.

## Leitregel

Gelöscht wird nur, was für einen der folgenden Zwecke nicht mehr benötigt
wird:

- Ausführung von `conclave desktop`, `conclave server`, `conclave web`
- Packaging mit `python -m build --sdist --wheel`
- Tests mit `python -m pytest`
- aktueller Personal-Release `v0.1.0`

Lokale Secrets, Backups und Workspace-Dateien werden separat behandelt und erst
nach expliziter Zusatzfreigabe gelöscht.

## Behalten

### Anwendung und Runtime

- `src/conclave/`
- `static/`
- `conclave-ui.html`
- `pyproject.toml`
- `pytest.ini`
- `README.md`
- `PROJECT.md`
- `LICENSE`
- `MANIFEST.in`

### Release- und Plattformmaterial

- `.github/workflows/ci.yml`
- `scripts/gen-openapi.py`
- `scripts/windows/`
- `scripts/linux/`
- `docs/index.md`
- `docs/beispiel-workflows.md`
- `docs/multi-agent-leitfaden.md`
- `docs/personal-multiplattform-implementierungsplan.md`
- `docs/personal-ui-architektur.md`
- `docs/phase-*.md`
- `docs/release-checkliste.md`
- `docs/release-notes-v0.1.0.md`
- `docs/sicherheit.md`
- `docs/assets/screenshots/`
- `docs/architektur/ports-adapter.md`
- `docs/flows/api-request.md`
- `docs/flows/orchestrierung.md`
- `docs/flows/workspace-directives.md`
- `docs/referenz/`
- `docs/contributor/pr-template.md`

### Tests

- `tests/`

Tests sind für die Ausführung des installierten Programms nicht nötig, aber
für diesen Release-Schnitt noch bewusst Teil des Worktrees.

## Phase A: Generierte Artefakte Entfernen

Sicher löschbar, weil jederzeit rekonstruierbar:

- `__pycache__/`
- `.pytest_cache/`
- `build/`
- `dist/`
- `src/conclave.egg-info/`
- alle `__pycache__/` unter `src/` und `tests/`
- alle `*.pyc`
- `debug.log`

Nach Phase A:

```powershell
python -m pytest
python -m build --sdist --wheel
```

## Phase B: Alte Enterprise-/Docker-/Guard-Oberfläche Entfernen

Diese Dateien gehören zum alten Server-/Enterprise-/Guard-Betrieb und sind
nicht Teil des Personal-Startpfads:

- `conclave_app.py`
- `guard.py`
- `Dockerfile`
- `docker-compose.yml`
- `docker-compose.override.yml`
- `.dockerignore`
- `deploy/`
- `scripts/autostart_app_native.ps1`
- `scripts/autostart-conclave.ps1`
- `scripts/demo-auto-loop.ps1`
- `scripts/fix_service.ps1`
- `scripts/gen-api-ref.py`
- `scripts/install_service.ps1`
- `scripts/install-autostart.ps1`
- `scripts/install-mcp-global.ps1`
- `scripts/restart-service.ps1`
- `scripts/start_app.ps1`
- `scripts/start_guard.ps1`
- `scripts/start_native.ps1`
- `scripts/sync-to-working.ps1`

Behalten werden nur:

- `scripts/gen-openapi.py`
- `scripts/windows/`
- `scripts/linux/`

Nach Phase B:

```powershell
python -m pytest
python -m build --sdist --wheel
```

## Phase C: Legacy-Dokumentation Entfernen

Diese Dokumente sind nicht im neuen Release-Manifest enthalten und beschreiben
den alten Enterprise-/DSGVO-/Go-Live-Stand:

- `docs/anleitung-anwender.md`
- `docs/anleitung-entwickler.md`
- `docs/api-dokumentation.md`
- `docs/dsgvo-massnahmenplan.md`
- `docs/dsgvo-refactoring-ergebnis.md`
- `docs/dsgvo-welle2-plan.md`
- `docs/go-live-plan.md`
- `docs/implementierungsplan.md`
- `docs/landkarte.md`
- `docs/nachrichtenfluss.md`
- `docs/pre-go-live-plan.md`
- `docs/sicherheitsregeln.md`
- `docs/universal-adapter-plan.md`
- `docs/adr/`
- `docs/betrieb/`
- `docs/legal/`
- `docs/architektur/domain-modelle.md`
- `docs/architektur/seams.md`
- `docs/contributor/architektur-regeln.md`
- `docs/contributor/test-guide.md`
- `docs/flows/dsgvo-lifecycle.md`

Nach Phase C:

```powershell
python -m pytest
python -m build --sdist --wheel
```

## Phase D: Lokale Laufzeitdaten Nur Nach Extra-Freigabe

Diese Dateien/Ordner sind nicht für den Quell-Release nötig, können aber
persönliche Daten oder Secrets enthalten:

- `.env`
- `workspace/`
- `backups/`
- `logs/`
- `mcp-filesystem.cmd`
- `migration-extras.tgz`
- `Conclave.code-workspace`

Empfehlung:

- `.env` nicht löschen, sondern ausserhalb des Repo sichern oder als lokale
  Datei behalten.
- `workspace/` und `backups/` nur löschen, wenn ihr Inhalt nicht mehr
  benötigt wird.
- `logs/`, `mcp-filesystem.cmd`, `migration-extras.tgz` und
  `Conclave.code-workspace` sind wahrscheinlich löschbar, brauchen aber wegen
  Lokalbezug eine explizite Freigabe.

## Phase E: Abschlussprüfung

Nach allen freigegebenen Bereinigungsschritten:

```powershell
python -m pytest
python -m build --sdist --wheel
python -m conclave.cli.main --help
```

Artefaktprüfung:

- Wheel enthält UI-Assets und CLI Entry Points.
- Source Distribution enthält aktuelle Release-Doku und Screenshots.
- Keine lokalen Workspace-Daten.
- Keine Datenbanken.
- Keine Keys.
- Keine Logs.
- Keine alten DSGVO-/Legal-Pfade.

## Freigabelogik

Empfohlene Reihenfolge:

1. Phase A ausführen.
2. Tests und Build prüfen.
3. Phase B ausführen.
4. Tests und Build prüfen.
5. Phase C ausführen.
6. Tests und Build prüfen.
7. Phase D einzeln entscheiden.
