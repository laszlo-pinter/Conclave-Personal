# Phase 4: Personal-API

**Status:** abgeschlossen  
**Datum:** 2026-08-11  
**Branch:** `personal-multiplatform`

## Ziel

Die HTTP-API wurde auf die Personal-Produktbereiche ausgerichtet. Die API ist
weiterhin kompatibel mit dem bestehenden Studio, bietet aber neue klare
Einstiegspunkte für Runs, Provider, lokale Settings, Backups und Judge-Läufe.

## Umgesetzt

- Neue Endpunkte:
  - `GET /health`
  - `GET /providers`
  - `POST /conversations/<conversation_id>/judge`
  - `DELETE /conversations/<conversation_id>/participants/<participant_id>`
  - `GET /settings`
  - `PUT /settings`
  - `POST /backup`
  - `POST /restore`
- Bestehende Run-Endpunkte bleiben Teil der Personal-API:
  - `GET /runs`
  - `GET /runs/<run_id>`
- Participant-Löschung ist jetzt sauber durchgezogen:
  - Application-Service
  - Repository-Port
  - SQLite-Repository
  - Postgres-Repository
  - API
- Provider-Endpunkt gibt Preset-Informationen und Key-Verfügbarkeit zurück,
  aber keine Secret-Werte.
- Settings-Endpunkt gibt lokale Runtime-Settings ohne Secrets zurück.
- `PUT /settings` kann den Workspace-Pfad für die laufende Session setzen.
- `POST /backup` erstellt ein lokales ZIP-Backup aus SQLite-DB und Workspace.
- `POST /restore` validiert ein Backup-Archiv, schreibt aber noch keine lokalen
  Daten. Restore bleibt damit bewusst nicht-destruktiv bis zur späteren
  Migrations-/Restore-Phase.
- OpenAPI-Schema und API-Referenz wurden neu generiert.

## Tests

Neue bzw. erweiterte Tests:

- `tests/api/test_personal_operations_api.py`
- `tests/api/test_api.py`
- `tests/application/test_register_participant.py`
- `tests/application/test_service_with_fakes.py`

Verifikation:

```powershell
python -m pytest
```

Ergebnis:

```text
710 passed, 1 skipped
```

## Einordnung

Phase 4 schneidet die API produktnah, ohne die UI komplett umzubauen. Die
nächste größere Veränderung liegt auf CLI- und Runtime-Ebene: `conclave
server`, `conclave web` und `conclave desktop` sollen die lokale Nutzung unter
Windows und Linux vereinheitlichen.
