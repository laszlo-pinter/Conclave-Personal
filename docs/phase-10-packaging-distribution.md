# Phase 10: Packaging und Distribution

**Status:** abgeschlossen  
**Datum:** 2026-08-11  
**Branch:** `personal-multiplatform`

## Ziel

Conclave Personal soll als lokales Werkzeug installierbar werden, ohne dass
Nutzer Docker, Repo-Layout oder manuelle Static-Dateien brauchen.

## Umgesetzt

- Basispaket enthaelt Runtime-Abhaengigkeiten:
  - `cryptography`
  - `flask`
  - `flask-limiter`
- Provider-SDKs bleiben optionale Extras:
  - `anthropic`
  - `openai`
  - `postgres`
  - `mcp`
- UI-Assets werden distributionsfaehig gefunden:
  - Source-Checkout: Repo-Root
  - installierte Distribution: `share/conclave`
  - Override: `CONCLAVE_ASSET_DIR`
- Release-Dateien werden ueber `pyproject.toml` und `MANIFEST.in`
  aufgenommen:
  - `conclave-ui.html`
  - `static/`
  - `scripts/windows/`
  - `scripts/linux/`
  - `docs/`
- Lokale Laufzeitdaten werden ausgeschlossen:
  - Workspace-Daten
  - Datenbanken
  - Keys
  - Logs
  - Python-Caches
- README auf den Release-Pfad aktualisiert:
  - `pipx install conclave`
  - `conclave desktop`

## Installationspfade

### Windows

```powershell
pipx install conclave
conclave desktop
```

Optionale Helfer:

```powershell
scripts\windows\start_desktop.ps1
scripts\windows\install_user_startup.ps1
```

### Linux

```bash
pipx install conclave
conclave desktop
```

Optionale Helfer:

```bash
scripts/linux/start_desktop.sh
scripts/linux/install_user_service.sh
```

## Build

```powershell
python -m build --sdist --wheel
```

Danach liegen Artefakte unter `dist/`.

## Bewusst Noch Nicht Umgesetzt

- Kein Windows-Installer.
- Kein AppImage oder `.deb`.
- Keine signierten Artefakte.
- Keine automatische Release-Pipeline.

Diese Punkte gehoeren in Phase 13 oder einen separaten Release-Schnitt.

## Tests

Neue Tests:

- `tests/runtime/test_assets.py`
- `tests/packaging/test_distribution_config.py`

Fokussierter Lauf:

```powershell
python -m pytest tests\runtime\test_assets.py tests\packaging\test_distribution_config.py tests\api\test_server_boot.py tests\api\test_openapi_contract.py
```

## Einordnung

Phase 10 macht Conclave installierbar und verhindert, dass die lokale Web-UI
beim Wechsel vom Source-Checkout zum Wheel verschwindet. Der eigentliche
Release-Prozess bleibt absichtlich leicht: Build, pruefen, Artefakt
veroeffentlichen.
