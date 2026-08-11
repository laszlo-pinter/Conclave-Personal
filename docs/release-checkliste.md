# Release-Checkliste

## Vor Dem Build

- `python -m pytest` ist gruen.
- CI-Matrix ist gruen:
  - Windows latest mit Python 3.11 und 3.12
  - Ubuntu latest mit Python 3.11 und 3.12
- `static/openapi.json` ist aktuell.
- README beschreibt `pipx install conclave` und `conclave desktop`.
- LICENSE ist vorhanden und `pyproject.toml` deklariert `LicenseRef-PolyForm-Noncommercial-1.0.0`.
- Release Notes sind aktuell.
- Security-Hinweise fuer lokale API sind aktuell.
- Beispiel-Workflows sind aktuell.
- Screenshots sind aktuell:
  - `docs/assets/screenshots/conclave-studio-desktop.png`
  - `docs/assets/screenshots/conclave-agents-desktop.png`
- Keine lokalen Secrets im Repo:
  - `.env`
  - `*.key`
  - `*.pem`
- Keine lokalen Laufzeitdaten im Artefakt:
  - `workspace/`
  - `*.db`
  - `*.db-wal`
  - `*.db-shm`
  - `logs/`
- Keine Python-Caches:
  - `__pycache__/`
  - `*.pyc`
- Keine alten `egg-info`-Artefakte.

## Build

```powershell
python -m build --sdist --wheel
```

## Smoke-Test

```powershell
python -m pip install --force-reinstall dist/conclave-*.whl
conclave --help
conclave desktop
conclave --json migrate-personal --from <alte-test-db> --to <temp-ziel-db> --dry-run
```

## Windows

- `conclave desktop` startet lokal.
- UI ist unter `http://127.0.0.1:<port>` erreichbar.
- Daten liegen unter `%LOCALAPPDATA%\Conclave`.
- Config und Secret-Key liegen unter `%APPDATA%\Conclave`.
- Workspace liegt standardmaessig unter `%USERPROFILE%\Conclave\workspace`.

## Linux

- `conclave desktop` startet lokal.
- UI ist unter `http://127.0.0.1:<port>` erreichbar.
- Daten liegen unter `$XDG_DATA_HOME/conclave` oder `~/.local/share/conclave`.
- Config liegt unter `$XDG_CONFIG_HOME/conclave` oder `~/.config/conclave`.
- Workspace liegt standardmaessig unter `~/Conclave/workspace`.

## Nach Dem Build

- Wheel enthaelt:
  - CLI Entry Points
  - `conclave-ui.html`
  - `static/`
  - Windows-/Linux-Skripte
- Source Distribution enthaelt:
  - `LICENSE`
  - Release-Doku
  - Screenshots
- Artefakt enthaelt keine lokalen Workspace-Daten.
- Artefakt enthaelt keine DSGVO-/Legal-Altpfade.
- `conclave migrate-personal --dry-run` liefert einen Report und schreibt keine Ziel-DB.
- Release-Notes nennen bekannte Einschraenkungen:
  - kein Installer
  - kein AppImage
  - Restore ist in v0.1.0 nur Backup-Validierung und schreibt keine Daten zurueck
  - Migration unterstuetzt aktuell SQLite, nicht Postgres
