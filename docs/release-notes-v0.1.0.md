# Release Notes: v0.1.0

**Status:** Alpha-Release-Kandidat  
**Datum:** 2026-08-11

## What Is Conclave?

Conclave v0.1.0 ist ein lokales Multi-Agent-Arbeitswerkzeug für einzelne
Nutzer. Es bringt mehrere KI-Modelle in strukturierte Conversations, gibt ihnen
explizite Rollen und macht ihre Arbeit über Runs nachvollziehbar.

Der Mensch bleibt Controller. Agents sind Participants. Runs machen
Zusammenarbeit sichtbar.

## Highlights

- Desktop-first Startpfad mit `conclave desktop`.
- Personal UI mit Studio, Agents, Workspace, Runs und Settings.
- Agentenmodell mit Rollen wie Writer, Reviewer, Critic, Researcher, Planner
  und Judge.
- Conversations mit mehreren Participants.
- Invoke, Stream, Orchestrierung, Auto-Loop und Judge-/Review-Flows.
- Lokale Workspace-Grenzen mit Hidden-Policy und Dateigrößenlimits.
- Runs und UsageRecords für Verlauf, Fehler, Dauer und Token-Nutzung.
- SQLite-Migration aus bestehenden lokalen Installationen.
- CI-Matrix für Windows und Ubuntu mit Python 3.11 und 3.12.
- Release-Artefakte als Wheel und Source Distribution.

## Installation

Der Zielpfad nach Veröffentlichung ist:

```bash
pipx install conclave
conclave desktop
```

Vor der PyPI-Veröffentlichung kann das gebaute Wheel installiert werden:

```bash
python -m build --sdist --wheel
python -m venv .venv-smoke
.venv-smoke/Scripts/pip install dist/conclave-0.1.0-py3-none-any.whl
.venv-smoke/Scripts/conclave --help
```

Unter Linux entsprechend mit `.venv-smoke/bin/...`.

## Supported Platforms

- Windows mit Python 3.11 und 3.12 in CI.
- Ubuntu/Linux mit Python 3.11 und 3.12 in CI.
- Lokale Runtime-Pfade folgen unter Linux XDG und unter Windows AppData /
  LocalAppData.

## Provider Support

First-class / getestet:

- OpenAI Responses
- OpenAI Chat Completions
- Anthropic
- Ollama

Built-in preset / kompatibel / experimentell:

- Gemini
- Mistral
- DeepSeek
- Qwen / DashScope
- Custom/OpenAI-compatible Endpoints

Remote-Provider erhalten die für den Modellaufruf erforderlichen
Prompt-/Kontextdaten. Ollama und lokale kompatible Endpunkte können
vollständig lokal betrieben werden.

## Security Model

- Standard-Bindung der lokalen API an `127.0.0.1`.
- API-Key-Pflicht im `production`-Modus.
- CORS-Allowlist.
- Workspace-Root-Restrictions, Path-Traversal-Schutz und Hidden-Path-Policy.
- Request-, Datei- und Workspace-Limits.
- Lokal verschlüsselte Agent-Provider-Secrets.
- Master-Key per `CONCLAVE_SECRET_KEY` oder `CONCLAVE_SECRET_KEY_FILE`.
- Security Headers, Log-Sanitization und RBAC-Guards im aktuellen API-Schnitt.

## License

Conclave v0.1.0 steht unter der PolyForm Noncommercial License 1.0.0.
Free for noncommercial use. Commercial use requires a separate license.
Commercial licensing: coming soon.

## Known Limitations

- v0.1.0 ist Alpha.
- Backup-Erstellung ist vorhanden; Restore validiert aktuell nur und schreibt
  noch keine Daten zurück.
- Provider-Kompatibilität variiert nach API, Modell, Account und Region.
- Remote-Provider übertragen Prompt-/Kontextdaten extern.
- Desktop-Modus nutzt die lokale Web-Anwendung im Browser.
- Erweiterte Multi-Agent-Orchestrierung bleibt in Teilen experimentell.
- Kein nativer Windows-Installer, kein AppImage, kein `.deb`, keine signierten
  Artefakte.
- Migration unterstützt aktuell SQLite, nicht Postgres.

## Breaking Changes / Migration

Gegenüber dem alten Enterprise-Stand wurden entfernt:

- Consent-Management.
- DPA-/AV-Vertragsverwaltung.
- DSGVO-Lifecycle-UI.
- Compliance-zentrierte API- und CLI-Oberflächen.

Bestehende lokale SQLite-Daten können explizit migriert werden:

```bash
conclave migrate-personal --from <alte-db> --dry-run
conclave migrate-personal --from <alte-db>
```

## Verification

- `python -m pytest`
- `python -m build --sdist --wheel`
- Installation aus dem gebauten Wheel in frischer Umgebung.
- `conclave --help`
- `conclave desktop`
- Golden-Path-Test mit Fake-Provider.
- Artefakt-Check ohne lokale Daten, Secrets, Logs, DBs, Caches und alte
  Enterprise-/DSGVO-Pfade.
- CLI-Hilfe enthält `migrate-personal`, aber keine Consent-/DPA-Kommandos.
- README, Security-Doku, Beispiel-Workflows, Konfiguration und Release-
  Checkliste sind aktuell.
