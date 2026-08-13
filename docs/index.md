# Conclave Dokumentation

## Was willst du tun?

### Getting Started
- [Schnellstart und Zielbild](../README.md) — Lokales Multi-Agent-Tool für Windows und Linux

### Concepts
- [Multi-Agent-Leitfaden](multi-agent-leitfaden.md) — Rollen, Workflows und Arbeitsmuster

### Workflows
- [Beispiel-Workflows](beispiel-workflows.md) — Review, Architektur, Workspace-Kontext und Judge
- [Provider-Smoke-Test](provider-smoke-test.md) — Claude, Gemini und GPT lokal prüfen

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

### Release
- [Release Notes v0.1.2](release-notes-v0.1.2.md) — Paketierte UI-Assets und robuster Runtime-Lookup
- [Release Notes v0.1.1](release-notes-v0.1.1.md) — PyPI-Metadaten und Projektlinks
- [Release Notes v0.1.0](release-notes-v0.1.0.md) — Erster Personal-Multiplattform-Schnitt
