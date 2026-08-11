# Phase 9: Workspace und lokale Sicherheit

**Status:** abgeschlossen  
**Datum:** 2026-08-11  
**Branch:** `personal-multiplatform`

## Ziel

Der Workspace bleibt ein lokaler Arbeitsraum fuer Kontext, Notizen und
Agent-Outputs, ohne unkontrollierte Dateizugriffe oder versehentliche
Grossimporte in Prompts.

## Umgesetzt

- Zentrale Workspace-Sicherheitsregeln:
  - `src/conclave/application/workspace_security.py`
- Gemeinsame Pfadauflösung fuer API, CLI und Agent-Directives.
- Path-Traversal und absolute Pfade werden zentral geblockt.
- Versteckte Pfade werden fuer UI/API/CLI und Agenten unsichtbar:
  - `.private/file.txt`
  - `.cache/...`
  - andere `.`-Komponenten
- Agent-Kontext ist begrenzt:
  - `@workspace/...`
  - `@read(...)`
- Schreibzugriffe sind begrenzt:
  - UI/API/CLI `workspace write`
  - Agent-Directive `@save(...)`
- Agent-Outputs bleiben unter:
  - `workspace/output/`
- Workspace-Listing liefert aktive Limits mit aus.
- Settings liefert aktive Workspace-Limits mit aus.
- UI zeigt die aktiven Workspace-Limits in Workspace und Settings.

## Neue Konfiguration

| Variable | Default | Zweck |
| --- | --- | --- |
| `CONCLAVE_WORKSPACE_AGENT_READ_LIMIT_BYTES` | `524288` | Limit fuer Agent-Kontextdateien |
| `CONCLAVE_WORKSPACE_UI_READ_LIMIT_BYTES` | `2097152` | Limit fuer UI/API/CLI-Lesezugriffe |
| `CONCLAVE_WORKSPACE_WRITE_LIMIT_BYTES` | `524288` | Limit fuer Schreibzugriffe |

## Bewusst Noch Nicht Umgesetzt

- Kontext-Budget pro Agent oder Conversation ist vorbereitet, aber noch nicht
  als eigenes Domain-Objekt umgesetzt.
- Restore bleibt weiterhin validierend, aber schreibt noch keine Daten zurueck.
- Backups sichern den Workspace weiterhin vollstaendig, auch wenn UI/API
  versteckte Pfade nicht anzeigen.

## Tests

Neue und aktualisierte Tests:

- `tests/application/test_workspace_security.py`
- `tests/application/test_workspace_directives.py`
- `tests/api/test_workspace_api.py`
- `tests/cli/test_handler.py`
- `tests/api/test_personal_operations_api.py`

Fokussierter Lauf:

```powershell
python -m pytest tests\application\test_workspace_security.py tests\application\test_workspace_directives.py tests\api\test_workspace_api.py tests\cli\test_handler.py tests\api\test_personal_operations_api.py
```

## Einordnung

Phase 9 macht den Workspace belastbarer fuer reale Nutzung: Agenten koennen
weiter gezielt Kontext lesen und Outputs speichern, aber nicht aus dem
Workspace ausbrechen, keine versteckten Bereiche sehen und keine grossen
Dateien still in Prompts ziehen.
