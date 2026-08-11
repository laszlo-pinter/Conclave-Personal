# Phase 7: UI-Umbau

**Status:** abgeschlossen  
**Datum:** 2026-08-11  
**Branch:** `personal-multiplatform`

## Ziel

Die Web-UI bildet die Personal-Informationsarchitektur sichtbar ab:
Studio, Agents, Workspace, Runs und Settings sind eigenstaendige
Arbeitsraeume. Die UI zeigt kein DSGVO-/Enterprise-Produkt mehr.

## Umgesetzt

- Globale Navigation auf fuenf Personal-Bereiche umgestellt:
  - Studio
  - Agents
  - Files
  - Runs
  - Settings
- Der separate Usage-Tab wurde entfernt.
- Usage ist jetzt Teil des Runs-Arbeitsraums.
- `Registry` wurde in der UI zu `Agents`.
- Agents hat eine eigene Hauptflaeche mit:
  - Agentenliste
  - Agent-Erstellen-Aktion
  - Provider-Status
  - Modelluebersicht
- Workspace hat eine eigene Hauptflaeche mit:
  - Dateiuebersicht
  - Upload
  - Text ablegen
- Settings hat eine eigene Hauptflaeche mit:
  - Runtime-Modus
  - Host und Port
  - DB-Provider und DB-Pfad
  - Workspace-Pfad
  - Provider-Key-Status
  - Backup-Erstellung
- Neues UI-Modul:
  - `static/js/features/settings.js`
- Bestehende Tab-Logik wurde auf die Personal-Arbeitsraeume angepasst.
- Ein bestehender Scope-Fehler in `static/js/features/agents.js` wurde
  beseitigt, sodass `testAgent()` wieder global erreichbar ist.

## Bewusst Noch Nicht Umgesetzt

- Der komplette Ziel-Split nach `static/js/core/` und Feature-Unterordnern
  ist vorbereitet, aber noch nicht vollzogen.
- Inline-Handler in bestehenden Render-Funktionen bleiben noch teilweise
  bestehen.
- Settings schreibt aktuell nur den Workspace-Pfad; weitere lokale Optionen
  folgen in Phase 9 und 10.

## Tests

Neue statische UI-Regression:

- `tests/ui/test_personal_ui_surface.py`

Fokussierter Lauf:

```powershell
python -m pytest tests\ui tests\api\test_personal_operations_api.py tests\api\test_personal_api_surface.py tests\cli\test_personal_cli_surface.py
```

## Einordnung

Phase 7 ist der erste sichtbare Produktschnitt. Sie ersetzt noch nicht die
gesamte Frontend-Architektur, schafft aber die Arbeitsraeume, auf denen die
naechsten Phasen sauber aufbauen koennen.
