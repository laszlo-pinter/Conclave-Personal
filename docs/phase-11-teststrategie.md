# Phase 11: Teststrategie

**Status:** abgeschlossen  
**Datum:** 2026-08-11  
**Branch:** `personal-multiplatform`

## Ziel

Die Testsuite soll den Personal-Umbau reproduzierbar absichern und auf den
beiden Zielplattformen Windows und Linux laufen.

## Umgesetzt

- GitHub-Actions-Workflow fuer die Personal-CI angelegt:
  - Windows latest
  - Ubuntu latest
  - Python 3.11
  - Python 3.12
- CI installiert Conclave mit allen Entwicklungs-Extras:
  - `python -m pip install -e ".[dev-all]"`
- CI fuehrt die komplette lokale Suite aus:
  - `python -m pytest`
- Separater Build-Job erstellt Release-Artefakte:
  - Source Distribution
  - Wheel
- Build-Job prueft die Artefakte auf Pflichtdateien:
  - `conclave-ui.html`
  - `static/openapi.json`
  - CLI Entry Points
- Build-Job blockiert lokale oder private Artefaktreste:
  - Workspace-Daten
  - Datenbanken
  - Keys
  - Logs
  - Python-Caches
  - DSGVO-/Legal-Altpfade
- Workflow-Guard-Tests sichern die CI-Konfiguration gegen Drift ab.

## Testmatrix

| Betriebssystem | Python |
| --- | --- |
| Ubuntu latest | 3.11 |
| Ubuntu latest | 3.12 |
| Windows latest | 3.11 |
| Windows latest | 3.12 |

## Lokaler Standardlauf

```powershell
python -m pytest
```

## Release-Lauf

```powershell
python -m build --sdist --wheel
```

Danach werden Wheel und Source Distribution auf Pflichtdateien und
ausgeschlossene Laufzeitdaten geprueft.

## Keine Echten Provider-Calls

Die Tests verwenden Fakes, Mocks oder In-Memory-Komponenten. Die CI setzt keine
Provider-Secrets und enthaelt einen Guard-Test, der das versehentliche Einbauen
echter Provider-API-Keys in den Workflow verhindert.

## Bewusst Noch Nicht Umgesetzt

- Kein End-to-End-Test gegen echte OpenAI-, Anthropic- oder Ollama-Instanzen.
- Kein UI-Browser-Smoke-Test mit Playwright.
- Kein signierter Release aus der CI.

Diese Punkte gehoeren in Phase 13 oder in einen separaten Release-Hardening-
Schnitt.

## Tests

Neue Tests:

- `tests/ci/test_github_actions.py`

Lokaler Lauf:

```powershell
python -m pytest tests\ci\test_github_actions.py
```

Verifikation am 2026-08-11:

- `python -m pytest tests\ci\test_github_actions.py`
  - `4 passed`
- `python -m pytest`
  - `771 passed, 1 skipped`
- `python -m build --sdist --wheel`
  - erfolgreich
- lokaler Artefakt-Check
  - keine fehlenden Pflichtdateien
  - keine Workspace-, DB-, Key-, Log- oder DSGVO-/Legal-Altpfade

## Einordnung

Phase 11 macht die bestehende Personal-Suite plattformfaehig und release-nah.
Damit ist der naechste Umbau nicht mehr nur lokal auf einer Maschine abgesichert,
sondern als Windows-/Linux-Matrix reproduzierbar.
