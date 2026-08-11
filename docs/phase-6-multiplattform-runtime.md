# Phase 6: Multiplattform-Runtime

**Status:** abgeschlossen  
**Datum:** 2026-08-11  
**Branch:** `personal-multiplatform`

## Ziel

Windows und Linux bekommen denselben Anwendungskern und eine zentrale Runtime
fuer lokale Pfade, Portwahl und Startverhalten.

## Umgesetzt

- Neues Runtime-Paket:
  - `src/conclave/runtime/platform_info.py`
  - `src/conclave/runtime/paths.py`
  - `src/conclave/runtime/process.py`
  - `src/conclave/runtime/browser.py`
  - `src/conclave/runtime/desktop.py`
- Plattformpfade zentralisiert:
  - Windows: `%APPDATA%`, `%LOCALAPPDATA%`, `%USERPROFILE%`
  - Linux: XDG-Defaults fuer Config, Data und State
- Defaults umgestellt:
  - SQLite-DB liegt nun im plattformkonformen Datenordner.
  - Secret-Key-Datei liegt nun im plattformkonformen Config-Ordner.
  - Workspace liegt standardmaessig unter `~/Conclave/workspace`.
- Runtime erstellt benoetigte Ordner beim Start.
- `conclave desktop` nutzt freie Portwahl, falls der bevorzugte Port belegt ist.
- `conclave web` oeffnet die UI im Browser ueber die Runtime-URL-Hilfen.
- Neue Startskripte:
  - `scripts/windows/start_server.ps1`
  - `scripts/windows/start_desktop.ps1`
  - `scripts/windows/install_user_startup.ps1`
  - `scripts/windows/install_service_nssm.ps1`
  - `scripts/windows/uninstall_service_nssm.ps1`
  - `scripts/linux/start_server.sh`
  - `scripts/linux/start_desktop.sh`
  - `scripts/linux/install_user_service.sh`
  - `scripts/linux/uninstall_user_service.sh`
  - `scripts/linux/conclave.service`
  - `scripts/linux/conclave.desktop`

## Tests

Neue Tests:

- `tests/runtime/test_paths.py`
- `tests/runtime/test_process.py`
- `tests/runtime/test_desktop.py`

Fokussierter Lauf:

```powershell
python -m pytest tests\runtime tests\cli\test_config.py tests\cli\test_config_unified.py tests\cli\test_main.py tests\cli\test_personal_cli_surface.py
```

Ergebnis:

```text
59 passed
```

## Einordnung

Phase 6 macht die lokale Runtime plattformfaehig, ohne bereits Installer,
AppImage oder ein natives Desktopfenster zu bauen. Die alten Skripte im
Hauptordner bleiben vorerst bestehen; die neuen Skripte liegen sauber getrennt
unter `scripts/windows` und `scripts/linux`.

## Naechster sinnvoller Schritt

Phase 7 kann jetzt die UI-Struktur weiter umbauen: Studio, Agents, Workspace,
Runs und Settings als klare Arbeitsraeume statt des aktuellen historisch
gewachsenen Monolithen.
