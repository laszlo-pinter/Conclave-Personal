# Phase 8: Provider und Agenten

**Status:** abgeschlossen  
**Datum:** 2026-08-11  
**Branch:** `personal-multiplatform`

## Ziel

Agenten und Provider sollen fuer Einzelnutzer verstaendlicher werden:
klare Rollen, aktuelle Presets, sichtbarer Key-Status und ein nutzbarer
Verbindungstest.

## Umgesetzt

- Produktrollen als Domain-Metadaten eingefuehrt:
  - Writer
  - Reviewer
  - Critic
  - Researcher
  - Planner
  - Judge
  - Custom
- Neuer API-Endpunkt:
  - `GET /agent-roles`
- Agent-Formular auf die neuen Rollen umgestellt.
- Presets bereinigt und mit Produktmetadaten erweitert:
  - `description`
  - `api_key_env`
  - `requires_api_key`
  - `recommended`
- Provider-Status erweitert:
  - lokal ja/nein
  - API-Key erforderlich ja/nein
  - API-Key verfuegbar ja/nein
  - empfohlener Provider ja/nein
- Ollama ist als lokaler First-Class-Pfad ohne API-Key markiert.
- Agent-Verbindungstest liefert jetzt strukturierte Details:
  - `status`
  - `provider`
  - `model`
  - `latency_ms`
  - `hint`
- Native Default-Modelle aktualisiert:
  - OpenAI: `gpt-5.6`
  - Anthropic: `claude-sonnet-5`
- OpenAPI-Spec neu generiert.

## Bewusst Noch Nicht Umgesetzt

- Der Verbindungstest macht weiterhin eine echte Mini-Anfrage an den Provider,
  wenn ein Adapter konfiguriert ist.
- Provider-Fehler werden jetzt strukturierter ausgegeben, aber noch nicht in
  eigene Fehlertypen normalisiert.
- Die UI nutzt die Rollen noch statisch aus dem Formular; der neue
  `/agent-roles` Endpunkt bereitet die spaetere dynamische Anzeige vor.

## Tests

Neue und aktualisierte Tests:

- `tests/domain/test_agent_roles.py`
- `tests/infrastructure/test_universal/test_presets.py`
- `tests/api/test_personal_operations_api.py`
- `tests/cli/test_handler.py`
- `tests/ui/test_personal_ui_surface.py`

Fokussierter Lauf:

```powershell
python -m pytest tests\domain\test_agent_roles.py tests\infrastructure\test_universal\test_presets.py tests\api\test_personal_operations_api.py tests\cli\test_handler.py tests\ui\test_personal_ui_surface.py
```

## Einordnung

Phase 8 macht Agenten staerker zu wiederverwendbaren Arbeitsrollen und
Provider staerker zu verstaendlichen, austauschbaren Anschluessen. Das ist die
Grundlage fuer Phase 9, in der Workspace-Kontext und lokale Sicherheit
geschaerft werden.
