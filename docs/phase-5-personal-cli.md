# Phase 5: Personal-CLI

**Status:** abgeschlossen  
**Datum:** 2026-08-11  
**Branch:** `personal-multiplatform`

## Ziel

Die CLI wurde als persönliches Steuerungs- und Debug-Werkzeug erweitert. Sie
deckt nun Runtime-Start, Conversations, Agents, Workspace, Runs, Usage und
Backup ab.

## Umgesetzt

- Neue Runtime-Kommandos:
  - `conclave server`
  - `conclave web`
  - `conclave desktop`
- Neue Arbeitskommandos:
  - `conclave auto-loop`
  - `conclave agent-test`
  - `conclave usage`
  - `conclave workspace list`
  - `conclave workspace read <path>`
  - `conclave workspace write <path> <text>`
  - `conclave backup`
- `agent-new` und `agent-edit` akzeptieren jetzt freie Provider-Namen und
  UniversalAdapter-Felder:
  - `--preset`
  - `--api-url`
  - `--response-path`
  - `--message-format`
- Workspace-Handler prüfen Pfade gegen `CONCLAVE_WORKSPACE`.
- Backup erstellt ein lokales ZIP mit Workspace-Dateien und optionaler SQLite-DB.
- CLI-Referenz angelegt:
  - `docs/referenz/cli.md`

## Grenzen

`conclave desktop` startet aktuell den lokalen Flask-Server und oeffnet die
Web-UI im Browser. Ein echtes plattformneutrales Runtime-Modul mit freier
Portwahl, Log-Pfaden und Desktopfenster folgt in Phase 6.

## Tests

Erweiterte Tests:

- `tests/cli/test_personal_cli_surface.py`
- `tests/cli/test_main.py`
- `tests/cli/test_handler.py`

Fokussierter Lauf:

```powershell
python -m pytest tests\cli\test_personal_cli_surface.py tests\cli\test_main.py tests\cli\test_handler.py
```

Ergebnis:

```text
53 passed
```

## Nächster sinnvoller Schritt

Phase 6 sollte die Multiplattform-Runtime einziehen: zentrale Pfade für
Windows/Linux, freie Portwahl, Browser-/Desktop-Start, Log-Verzeichnisse und
plattformgetrennte Startskripte.
