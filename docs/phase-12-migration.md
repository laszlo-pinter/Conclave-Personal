# Phase 12: Migration Aus Bestehenden Installationen

**Status:** abgeschlossen  
**Datum:** 2026-08-11  
**Branch:** `personal-multiplatform`

## Ziel

Bestehende lokale SQLite-Daten sollen explizit und nachvollziehbar in das neue
Conclave-Personal-Schema uebernommen werden.

Die Migration startet nicht automatisch beim ersten Start. Der Nutzer fuehrt sie
bewusst per CLI aus.

## Kommando

```powershell
conclave migrate-personal --from <alte-db> [--to <ziel-db>] [--backup-dir <dir>]
```

Beispiele:

```powershell
conclave migrate-personal --from C:\alt\conclave.db
conclave migrate-personal --from C:\alt\conclave.db --to C:\neu\conclave.db
conclave --json migrate-personal --from C:\alt\conclave.db --dry-run
```

Wenn `--to` fehlt, verwendet Conclave die aktive lokale Personal-Datenbank aus
der Runtime-Konfiguration.

## Uebernommen

- Conversations
- Messages
- Participants
- Agents
- Audit-/Usage-Daten
- vorhandene Runs und UsageRecords, falls die Quelle sie bereits enthaelt

Audit-Eintraege werden zusaetzlich in Personal-Runs uebersetzt:

| Audit-Operation | Run-Kind |
| --- | --- |
| `invoke_*` | `invoke` |
| `stream_*` | `stream` |
| `orchestrate*` | `orchestrate` |
| `auto*` | `auto_loop` |
| `judge*` | `judge` |

## Bewusst Ignoriert

- Consent-Tabellen
- DPA-/AV-Tabellen
- Transfer-Policy-Tabellen

Diese Daten gehoeren zum alten Enterprise-/Compliance-Modell und werden im
Personal-Produkt nicht fortgefuehrt.

## Sicherheitsverhalten

- Quelle und Ziel duerfen nicht dieselbe Datei sein.
- Existiert die Ziel-DB bereits, wird vor dem Schreiben ein Backup angelegt.
- Die Migration ist idempotent:
  - vorhandene IDs werden uebersprungen
  - doppelte Laeufe erzeugen keine doppelten Conversations oder Messages
- `--dry-run` erzeugt nur einen Bericht und schreibt keine Ziel-DB.

## Report

Der Bericht enthaelt:

- Quelle
- Ziel
- Backup-Pfad
- uebernommene Zeilen je Tabelle
- uebersprungene Zeilen je Tabelle
- bewusst ignorierte Tabellen
- aus Audit erzeugte Runs
- Hinweise

Mit `--json` wird der Bericht maschinenlesbar ausgegeben.

## Bewusst Noch Nicht Umgesetzt

- Keine Migration aus Postgres.
- Kein Re-Encrypt von Agent-API-Keys mit einem neuen Secret.
- Kein Workspace-Dateiimport aus beliebigen alten Projektordnern.
- Kein automatischer First-Start-Migrationsdialog in der UI.

Diese Punkte gehoeren in ein spaeteres Migration-Hardening oder in Phase 13.

## Tests

Neue Tests:

- `tests/application/test_personal_migration.py`
- `tests/cli/test_migrate_personal.py`

Fokussierter Lauf:

```powershell
python -m pytest tests\application\test_personal_migration.py tests\cli\test_migrate_personal.py tests\cli\test_personal_cli_surface.py
```

Verifikation am 2026-08-11:

- fokussierter Lauf
  - `17 passed`

## Einordnung

Phase 12 schliesst die groesste Luecke zwischen Umbau und Veroeffentlichung:
Bestehende lokale Nutzer koennen ihre Kernarbeit uebernehmen, ohne das alte
Compliance-Modell mitzuschleppen.
