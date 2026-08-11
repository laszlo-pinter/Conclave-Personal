# Phase 3: Personal-Domain

**Status:** abgeschlossen  
**Datum:** 2026-08-11  
**Branch:** `personal-multiplatform`

## Ziel

Conclave bekommt eine produktnahe Personal-Domain fuer Arbeitslaeufe. Die alte
Audit-Technik bleibt vorerst als kompatible Usage-Quelle bestehen, aber neue
Funktionen orientieren sich an `Run` und `UsageRecord`.

## Umgesetzt

- Neue Domain-Modelle:
  - `Run`
  - `UsageRecord`
- Neuer Application-Port:
  - `RunRepository`
- Neue Repositories:
  - `SQLiteRunRepository`
  - `PostgresRunRepository`
- Schema erweitert:
  - `runs`
  - `usage_records`
- Migration ergaenzt:
  - `005_personal_runs`
- `ConversationFlowService` schreibt Runs fuer:
  - `invoke_participant`
  - `invoke_with_floor`
  - `stream_participant`
  - `async_complete_participant`
  - `async_stream_participant`
- Erfolgreiche Runs enthalten:
  - Typ
  - Conversation
  - beteiligte Participants
  - Start-/Endzeit
  - Status
  - Provider-/Modell-/Token-Usage, sofern verfuegbar
- Fehlgeschlagene Runs enthalten:
  - Status `failed`
  - Fehlerklasse im Feld `error`
- Bootstrap und API-Server verdrahten das RunRepository automatisch.
- Neue API:
  - `GET /runs`
  - `GET /runs/<run_id>`
- Neue CLI:
  - `conclave runs`
- Minimale UI-Erweiterung:
  - eigener `Runs`-Tab
  - Run-Liste in der Sidebar
  - Run-Historie im Hauptbereich
- OpenAPI und API-Referenz wurden neu generiert.

## Tests

Neue Tests:

- `tests/domain/test_run.py`
- `tests/infrastructure/sqlite/test_run_repository.py`
- `tests/application/test_run_logging.py`
- `tests/api/test_runs_api.py`

Verifikation:

```powershell
python -m pytest
```

Ergebnis:

```text
699 passed, 1 skipped
```

## Technische Einordnung

`AuditEntry` und `audit_log` wurden noch nicht entfernt, weil die bestehende
Usage-Auswertung darauf basiert und stabil funktioniert. Die neue Run-Schicht
ist bewusst parallel eingefuehrt. In einer spaeteren Phase kann Usage komplett
auf `usage_records` umgestellt und `audit_log` intern umbenannt oder entfernt
werden.

## Naechster sinnvoller Schritt

Phase 4 sollte die Personal-API weiter schaerfen: vorhandene Routen in klare
Produktbereiche gliedern, `/runs` in der OpenAPI-Spec mit Schemas beschreiben
und Settings-/Backup-Endpunkte vorbereiten.
