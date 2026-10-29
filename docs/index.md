# Conclave Documentation

## What Do You Want To Do?

### Getting Started
- [Quickstart and product shape](../README.md) - Local multi-agent tool for Windows and Linux

### Concepts
- [Multi-agent guide](multi-agent-leitfaden.md) - Roles, workflows, and working patterns

### Workflows
- [Example workflows](beispiel-workflows.md) - Writing, architecture, workspace context, and multi-agent runs
- [Provider smoke test](provider-smoke-test.md) - Check Claude, Gemini, GPT, and DeepSeek locally
- [Working with Kanzo](mit-kanzo-arbeiten.md) - Work packages on a Kanzo board, second opinions from Conclave

### Product UI
- [Personal UI architecture](personal-ui-architektur.md) - Studio, Agents, Workspace, Runs, Settings

### Security
- [Security](sicherheit.md) - Local API, secrets, workspace, and release artifacts

### Reference
- [API reference](referenz/api.md) - Current Personal API
- [CLI reference](referenz/cli.md) - Current Personal CLI
- [Configuration](referenz/konfiguration.md) - Runtime paths, environment variables, and TOML fallback

### Architecture
- [Flow: API request](flows/api-request.md) - From HTTP call to LLM response
- [Flow: orchestration](flows/orchestrierung.md) - Sequential, parallel, auto-loop
- [Flow: workspace directives](flows/workspace-directives.md) - `@workspace`, `@read`, and `@save`
- [Ports & adapters](architektur/ports-adapter.md) - Interfaces, ProviderProfiles, ResilientAdapter

### Release
- [Release Notes v0.5.1](release-notes-v0.5.1.md) - File viewer in the Files area
- [Release Notes v0.5.0](release-notes-v0.5.0.md) - Separate human and agent access
- [Release Notes v0.4.0](release-notes-v0.4.0.md) - Consultations: second opinions on Kanzo tickets
- [Release Notes v0.3.0](release-notes-v0.3.0.md) - Context transparency: context chip, preview before a call, per-agent message limit
- [Release Notes v0.2.3](release-notes-v0.2.3.md) - Chat rules are saved with SQLite
- [Release Notes v0.2.2](release-notes-v0.2.2.md) - Streaming for all preset formats, correct token usage
- [Release Notes v0.2.1](release-notes-v0.2.1.md) - MCP server on the MCP Python SDK 2.x
- [Release Notes v0.2.0](release-notes-v0.2.0.md) - Security release: XSS protection, mandatory API token, CSP, per-thread SQLite, waitress
- [Release Notes v0.1.20](release-notes-v0.1.20.md) - Live parallel orchestration responses in the desktop UI
- [Release Notes v0.1.19](release-notes-v0.1.19.md) - Workspace tool-event provenance for read/write actions
- [Release Notes v0.1.18](release-notes-v0.1.18.md) - Delete cleanup, runtime logs, DeepSeek fixes, and UI polish
- [Release Notes v0.1.17](release-notes-v0.1.17.md) - Restore, orchestration rotation, and tool boundary cleanup
- [Release Notes v0.1.16](release-notes-v0.1.16.md) - Switchable German/English desktop UI
- [Release Notes v0.1.5](release-notes-v0.1.5.md) - English public documentation surface
- [Release Notes v0.1.4](release-notes-v0.1.4.md) - README origin notice placement for PyPI
- [Release Notes v0.1.3](release-notes-v0.1.3.md) - README and sdist corrections after release
- [Release Notes v0.1.2](release-notes-v0.1.2.md) - Packaged UI assets and robust runtime lookup
- [Release Notes v0.1.1](release-notes-v0.1.1.md) - PyPI metadata and project links
- [Release Notes v0.1.0](release-notes-v0.1.0.md) - First Personal multiplatform surface
