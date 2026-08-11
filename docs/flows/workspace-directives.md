# Flow: Workspace-Directives - @workspace, @read, @save

**Auslöser:** User-Message mit @workspace/datei oder Agent-Antwort mit @read()/@save()

**Vorbedingung:** Ein lokaler Workspace ist konfiguriert. Ohne
`CONCLAVE_WORKSPACE` nutzt Conclave die Plattformdefaults aus
`src/conclave/runtime/paths.py`: unter Windows `%USERPROFILE%\Conclave\workspace`,
unter Linux `~/Conclave/workspace`.

## 1. @workspace/datei — User referenziert Dateien

- **Datei:** `application/conversation_flow.py:_expand_workspace_refs()`
- **Trigger:** Vor jedem Provider-Call (im Snapshot, nicht in der DB)
- **Regex:** `@work(?:space|place)/([\w./-]+)` — matcht @workspace/ und @workplace/
- **Aktion:** Dateiinhalt wird inline eingefügt als Markdown-Codeblock
- **Security:** `application/workspace_security.py:resolve_workspace_path()` blockt absolute Pfade und Traversal. `is_agent_visible()` blendet versteckte Pfadkomponenten aus.
- **Limits:** `CONCLAVE_WORKSPACE_AGENT_READ_LIMIT_BYTES`, Default `524288`
- **Fehler:** Pfad nicht erlaubt, Datei nicht gefunden, Dateigröße überschreitet das Limit, Datei nicht lesbar
- **Test:** `tests/application/test_workspace_directives.py:TestExpandWorkspaceRefsPathTraversal`

## 2. @read(pfad) — Agent liest Dateien

- **Datei:** `application/conversation_flow.py:_process_agent_directives()`
- **Trigger:** Nach Agent-Antwort, vor Message-Persistierung
- **Regex:** `@read\(([^)]+)\)`
- **Aktion:** Ersetzt @read(pfad) durch Dateiinhalt als Markdown-Codeblock
- **Security:** Gleiche `resolve_workspace_path()`-/Hidden-Path-Prüfung wie `@workspace`
- **Scope:** Gesamter Workspace (lesend)
- **Limits:** `CONCLAVE_WORKSPACE_AGENT_READ_LIMIT_BYTES`, Default `524288`
- **Test:** `tests/application/test_workspace_directives.py:TestProcessAgentDirectivesReadPathTraversal`

## 3. @save(datei)...@endsave — Agent schreibt Dateien

- **Datei:** `application/conversation_flow.py:_process_agent_directives()`
- **Trigger:** Nach Agent-Antwort, vor Message-Persistierung
- **Regex:** `@save\(([^)]+)\)\s*\n(.*?)(?:@endsave|$)` (DOTALL)
- **Aktion:** Schreibt Content zwischen @save und @endsave in workspace/output/
- **Security:** `resolve_output_path()` begrenzt Schreibzugriffe auf `workspace/output/`
- **Scope:** Nur workspace/output/ (schreibend) — Rest ist schreibgeschützt
- **Limits:** `CONCLAVE_WORKSPACE_WRITE_LIMIT_BYTES`, Default `524288`
- **Ersetzung:** `[Datei gespeichert: @workspace/output/dateiname]` im Chat
- **Test:** `tests/application/test_workspace_directives.py:TestProcessAgentDirectivesSavePathTraversal`

## 4. Workspace-API (HTTP-Endpoints)

- **GET /workspace** — Listet alle Dateien (Pfad, Größe, Änderungsdatum)
- **GET /workspace/pfad** — Liest Dateiinhalt (UTF-8, 415 bei Binär)
- **POST /workspace/pfad** — Schreibt Datei (Body: {content})
- **DELETE /workspace/pfad** — Löscht Datei
- **Security:** `resolve_workspace_path()` und `is_hidden_workspace_path()` in `application/workspace_security.py`
- **Limits:** Lesen über UI/API: `CONCLAVE_WORKSPACE_UI_READ_LIMIT_BYTES`, Schreiben: `CONCLAVE_WORKSPACE_WRITE_LIMIT_BYTES`
- **Test:** `tests/api/test_workspace_api.py`

## 5. Workspace-Info im System-Prompt

- **Datei:** `infrastructure/universal/adapter.py:_build_workspace_info()`
- **Aktion:** Listet alle Dateien im Workspace als Teil des System-Prompts
- **Inhalt:** Anleitung für @workspace (lesen), @read (Agent liest), @save (Agent schreibt)
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
_process_agent_directives() → Dateiinhalt eingefügt → gespeichert in DB
        |
Agent antwortet mit @save(ergebnis.md)\n...\n@endsave
        |
        v
_process_agent_directives() → Datei in workspace/output/ geschrieben
```

**Code-Referenzen:**
- Lesen/Expandieren: `src/conclave/application/conversation_flow.py:_expand_workspace_refs()`
- Agent-Direktiven: `src/conclave/application/conversation_flow.py:_process_agent_directives()`
- Security: `src/conclave/application/workspace_security.py`
- API: `src/conclave/api/app.py` Workspace-Endpunkte
- System-Prompt: `src/conclave/infrastructure/universal/adapter.py:_build_workspace_info()`
- Tests: `tests/application/test_workspace_directives.py`, `tests/api/test_workspace_api.py`

**Zuletzt verifiziert:** 2026-08-11 im Personal-Multiplattform-Schnitt
