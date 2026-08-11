# Phase 0 Baseline

Datum: 2026-08-11

## Sicherung

- Sicherungsbranch: `legacy-enterprise-dsgvo`
- Sicherungstag: `v0-enterprise-archive`
- Neuer Arbeitsbranch: `personal-multiplatform`

Branch und Tag zeigen auf den Commit-Stand vor dem aktiven Umbau im
Personal-/Multiplattform-Branch.

## Repo-Hygiene

Getrackte generierte Artefakte wurden aus dem Git-Index entfernt:

- `src/conclave.egg-info/`
- `src/**/__pycache__/`
- `tests/**/__pycache__/`

Die Dateien wurden nicht lokal gelöscht. Sie bleiben durch `.gitignore`
aus der Versionskontrolle heraus.

Nicht automatisch bereinigt:

- `workspace/`
- `migration-extras.tgz`
- lokale Editor-/Claude-Konfigurationsdateien

Diese Dateien brauchen vor dem Release eine bewusste Entscheidung.

## Testumgebung

Aktives Python:

```text
Python 3.14.6
```

Installierte Dev-Abhängigkeiten:

```text
python -m pip install -e ".[dev-all]"
```

## Baseline-Testlauf

Kommando:

```text
python -m pytest tests/ -q
```

Ergebnis:

```text
760 passed, 1 skipped in 13.74s
```

## Stabilisierung in Phase 0

Beim ersten Baseline-Testlauf trat ein Fehler im ParallelOrchestrator auf:

- Test: `tests/application/test_parallel_sync_adapters.py::test_later_group_sees_earlier_group_responses`
- Ursache: Participants innerhalb derselben Parallelgruppe konnten unter
  bestimmten Timing-Bedingungen bereits Antworten anderer Participants aus
  derselben Gruppe sehen.
- Fix: Parallelgruppen nutzen jetzt einen gemeinsamen Snapshot und persistieren
  erfolgreiche Antworten erst nach Abschluss der Gruppe in stabiler Reihenfolge.

Damit ist das erwartete Verhalten wiederhergestellt:

- innerhalb einer Gruppe: blind-parallel
- zwischen Gruppen: sequenziell sichtbar

