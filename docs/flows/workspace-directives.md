# Flow: Workspace-Directives — @workspace, @read, @save

**Ausloeser:** User-Message mit @workspace/datei oder Agent-Antwort mit @read()/@save()

**Vorbedingung:** CONCLAVE_WORKSPACE Env-Var gesetzt (Default: /workspace), Dateisystem-Zugriff

## 1. @workspace/datei — User referenziert Dateien

- **Datei:** `application/conversation_flow.py:_expand_workspace_refs()`
- **Trigger:** Vor jedem Provider-Call (im Snapshot, nicht in der DB)
- **Regex:** `@work(?:space|place)/([\w./-]+)` — matcht @workspace/ und @workplace/
- **Aktion:** Dateiinhalt wird inline eingefuegt als Markdown-Codeblock
- **Security:** `os.path.normpath(os.path.join(workspace, filepath))` + `startswith(os.path.abspath(workspace) + os.sep)` — blockt absolute Pfade und Traversal
- **Fehler:** `[FEHLER: Pfad nicht erlaubt]`, `[FEHLER: datei nicht gefunden]`, `[FEHLER: datei nicht lesbar]`
- **Test:** `tests/application/test_workspace_directives.py:TestExpandWorkspaceRefsPathTraversal`

## 2. @read(pfad) — Agent liest Dateien

- **Datei:** `application/conversation_flow.py:_process_agent_directives()`
- **Trigger:** Nach Agent-Antwort, vor Message-Persistierung
- **Regex:** `@read\(([^)]+)\)`
- **Aktion:** Ersetzt @read(pfad) durch Dateiinhalt als Markdown-Codeblock
- **Security:** Gleiche abspath-Pruefung wie @workspace
- **Scope:** Gesamter Workspace (lesend)
- **Test:** `tests/application/test_workspace_directives.py:TestProcessAgentDirectivesReadPathTraversal`

## 3. @save(datei)...@endsave — Agent schreibt Dateien

- **Datei:** `application/conversation_flow.py:_process_agent_directives()`
- **Trigger:** Nach Agent-Antwort, vor Message-Persistierung
- **Regex:** `@save\(([^)]+)\)\s*\n(.*?)(?:@endsave|$)` (DOTALL)
- **Aktion:** Schreibt Content zwischen @save und @endsave in workspace/output/
- **Security:** Gleiche abspath-Pruefung, aber gegen output_dir (nicht gesamter Workspace)
- **Scope:** Nur workspace/output/ (schreibend) — Rest ist schreibgeschuetzt
- **Ersetzung:** `[Datei gespeichert: @workspace/output/dateiname]` im Chat
- **Test:** `tests/application/test_workspace_directives.py:TestProcessAgentDirectivesSavePathTraversal`

## 4. Workspace-API (HTTP-Endpoints)

- **GET /workspace** — Listet alle Dateien (Pfad, Groesse, Aenderungsdatum)
- **GET /workspace/pfad** — Liest Dateiinhalt (UTF-8, 415 bei Binaer)
- **POST /workspace/pfad** — Schreibt Datei (Body: {content})
- **DELETE /workspace/pfad** — Loescht Datei
- **Security:** `_safe_workspace_path()` in `api/app.py` — gleiche abspath-Pruefung
- **Test:** `tests/api/test_workspace_api.py`

## 5. Workspace-Info im System-Prompt

- **Datei:** `infrastructure/universal/adapter.py:_build_workspace_info()`
- **Aktion:** Listet alle Dateien im Workspace als Teil des System-Prompts
- **Inhalt:** Anleitung fuer @workspace (lesen), @read (Agent liest), @save (Agent schreibt)
- **Trigger:** Bei jedem Provider-Call (in _build_system_prompt)

## Datenfluss

```
User schreibt @workspace/datei.md
        |
        v
_expand_workspace_refs() → Dateiinhalt inline → Provider sieht Inhalt
        |
        v
Agent antwortet mit @read(andere-datei.py)
        |
        v
_process_agent_directives() → Dateiinhalt eingefuegt → gespeichert in DB
        |
Agent antwortet mit @save(ergebnis.md)\n...\n@endsave
        |
        v
_process_agent_directives() → Datei in workspace/output/ geschrieben
```

**Code-Referenzen:**
- Lesen/Expandieren: `src/conclave/application/conversation_flow.py:_expand_workspace_refs()`
- Agent-Direktiven: `src/conclave/application/conversation_flow.py:_process_agent_directives()`
- API: `src/conclave/api/app.py:_safe_workspace_path()` + 4 Endpoints
- System-Prompt: `src/conclave/infrastructure/universal/adapter.py:_build_workspace_info()`
- Tests: `tests/application/test_workspace_directives.py`, `tests/api/test_workspace_api.py`

**Zuletzt verifiziert:** 05.04.2026 durch CC
