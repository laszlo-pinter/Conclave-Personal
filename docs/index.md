# Conclave Dokumentation

## Was willst du tun?

### Getting Started
- [Schnellstart und Zielbild](../README.md) — Lokales Multi-Agent-Tool für Windows und Linux

### Concepts
- [Multi-Agent-Leitfaden](multi-agent-leitfaden.md) — Rollen, Workflows und Arbeitsmuster

### Workflows
- [Beispiel-Workflows](beispiel-workflows.md) — Review, Architektur, Workspace-Kontext und Judge

### Product UI
- [Personal UI Architektur](personal-ui-architektur.md) — Studio, Agents, Workspace, Runs, Settings

### Security
- [Sicherheit](sicherheit.md) — Lokale API, Secrets, Workspace und Release-Artefakte

### Reference
- [API-Referenz](referenz/api.md) — Aktuelle Personal-API
- [CLI-Referenz](referenz/cli.md) — Aktuelle Personal-CLI
- [Konfiguration](referenz/konfiguration.md) — Runtime-Pfade, Env-Vars und TOML-Fallback

### Architecture
- [Flow: API-Request](flows/api-request.md) — Vom HTTP-Call zur LLM-Antwort
- [Flow: Orchestrierung](flows/orchestrierung.md) — Sequentiell, parallel, auto-loop
- [Flow: Workspace-Directives](flows/workspace-directives.md) — `@workspace`, `@read` und `@save`
- [Ports & Adapter](architektur/ports-adapter.md) — Interfaces, ProviderProfiles, ResilientAdapter

### Development History
- [Personal-Multiplattform-Implementierungsplan](personal-multiplattform-implementierungsplan.md) — Umbau zu einem lokalen Multi-Agent-Tool für Windows und Linux
- [Phase-0-Baseline](phase-0-baseline.md) — Sicherung, Repo-Hygiene und Testbaseline für den Umbau
- [Phase-1-Produktziel](phase-1-produktziel.md) — Produktziel, Doku-Neuschnitt und Personal-Arbeitsräume
- [Phase-2-Personal-Surface](phase-2-personal-surface.md) — API, CLI, MCP und UI ohne Enterprise-Oberfläche
- [Phase-3-Personal-Domain](phase-3-personal-domain.md) — Runs und UsageRecords als neue Arbeitslauf-Historie
- [Phase-4-Personal-API](phase-4-personal-api.md) — Personal-Endpunkte für Runs, Provider, Settings, Backup und Judge
- [Phase-5-Personal-CLI](phase-5-personal-cli.md) — CLI für Runtime, Workspace, Runs, Usage und Backup
- [Phase-6-Multiplattform-Runtime](phase-6-multiplattform-runtime.md) — Windows-/Linux-Pfade, Portwahl und Startskripte
- [Phase-7-UI-Umbau](phase-7-ui-umbau.md) — Studio, Agents, Workspace, Runs und Settings als Personal-Arbeitsräume
- [Phase-8-Provider-Agenten](phase-8-provider-agenten.md) — Rollen, Presets, Provider-Status und Agent-Verbindungstest
- [Phase-9-Workspace-Sicherheit](phase-9-workspace-sicherheit.md) — Workspace-Grenzen, Hidden-Policy und Dateigrößenlimits
- [Phase-10-Packaging-Distribution](phase-10-packaging-distribution.md) — pipx/Wheel-Paket, UI-Assets und Release-Artefakte
- [Phase-11-Teststrategie](phase-11-teststrategie.md) — Windows-/Linux-CI, Python-Matrix und Artefakt-Guards
- [Phase-12-Migration](phase-12-migration.md) — Explizite SQLite-Migration vom Altbestand ins Personal-Schema
- [Phase-13-Release-Vorbereitung](phase-13-release-vorbereitung.md) — README, Lizenz, Screenshots, Security und Release Notes
- [Release-Checkliste](release-checkliste.md) — Build-, Smoke- und Artefaktprüfungen
- [Release Notes v0.1.0](release-notes-v0.1.0.md) — Erster Personal-Multiplattform-Schnitt

### Contributor — Code beisteuern
- [PR-Template](contributor/pr-template.md) — Pflichtfelder, Docs-Debt
