# Flow: Workspace-Directives - @workspace, @read, @save

**Auslöser:** User-Message mit @workspace/datei oder Agent-Antwort mit @read()/@save()

**Vorbedingung:** Ein lokaler Workspace ist konfiguriert. Ohne
`CONCLAVE_WORKSPACE` nutzt Conclave die Plattformdefaults aus
`src/conclave/runtime/paths.py`: unter Windows `%USERPROFILE%\Conclave\workspace`,
unter Linux `~/Conclave/workspace`. Das gilt für alle Einstiegspunkte
(CLI-Kommandos, `conclave server`/`desktop`, `conclave-api`), siehe
`application/workspace_security.py:workspace_root()`.

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

- **Datei:** `application/conversation_flow.py:_process_agent_directives_for_context()`
- **Trigger:** Nach Agent-Antwort, vor Message-Persistierung
- **Regex:** `@read\(([^)]+)\)`
- **Aktion:** Ersetzt @read(pfad) durch Dateiinhalt als Markdown-Codeblock
- **Security:** Gleiche `resolve_workspace_path()`-/Hidden-Path-Prüfung wie `@workspace`
- **Scope:** Gesamter Workspace (lesend)
- **Limits:** `CONCLAVE_WORKSPACE_AGENT_READ_LIMIT_BYTES`, Default `524288`
- **Protokoll:** Der Leseversuch erzeugt ein `tool_events`-DB-Ereignis
  mit `tool=workspace.read` und `status=succeeded|failed`.
- **Ersetzung:** Im Runtime-Pfad wird zusätzlich
  `[tool_event:<event_id>]` in der Message referenziert. Die UI blendet
  diese technische Referenz aus und zeigt das Tool-Ereignis separat an.
- **Test:** `tests/application/test_workspace_directives.py:TestProcessAgentDirectivesReadPathTraversal`
  und `tests/cli/test_bootstrap.py:test_build_service_records_workspace_read_tool_event`

## 3. @save(datei)...@endsave — Agent schreibt Dateien

- **Datei:** `application/conversation_flow.py:_process_agent_response()` -> `_process_agent_directives_for_context()`
  (`_process_agent_directives()` ist nur ein Wrapper ohne Tool-Events, der im Runtime-Pfad nicht genutzt wird)
- **Trigger:** Nach Agent-Antwort, vor Message-Persistierung
- **Regex:** `@save\(([^)]+)\)\s*\n(.*?)(?:@endsave|$)` (DOTALL)
- **Aktion:** Schreibt Content zwischen @save und @endsave in workspace/output/. Fehlt `@endsave`, wird bis zum Ende der Antwort gespeichert.
- **Security:** `resolve_output_path()` begrenzt Schreibzugriffe auf `workspace/output/`
- **Scope:** Nur workspace/output/ (schreibend) — für Agent-Directives ist der Rest schreibgeschützt. UI/API/CLI dürfen überall im Workspace schreiben (außer versteckten Pfaden), siehe Abschnitt 4.
- **Limits:** `CONCLAVE_WORKSPACE_WRITE_LIMIT_BYTES`, Default `524288`
- **Protokoll:** Der Schreibversuch erzeugt ein `tool_events`-DB-Ereignis
  mit `tool=workspace.save` und `status=succeeded|failed`.
- **Ersetzung:** Im Runtime-Pfad wird die Agent-Antwort durch
  `[tool_event:<event_id>]` referenziert. Der Agent beschreibt den
  Seiteneffekt nicht selbst; das Backend protokolliert das Ergebnis.
- **Test:** `tests/application/test_workspace_directives.py:TestProcessAgentDirectivesSavePathTraversal`
  und `tests/cli/test_bootstrap.py:test_build_service_records_workspace_save_tool_event`

## 4. Workspace-API (HTTP-Endpoints)

- **GET /workspace** — Listet alle Dateien (Pfad, Größe, Änderungsdatum)
- **GET /workspace/pfad** — Liest Dateiinhalt (UTF-8, 415 bei Binär)
- **POST /workspace/pfad** — Schreibt Datei (Body: {content}) an beliebiger Stelle im Workspace, nicht nur in `output/`
- **DELETE /workspace/pfad** — Löscht Datei
- **Security:** `resolve_workspace_path()` und `is_hidden_workspace_path()` in `application/workspace_security.py`
- **Limits:** Lesen über UI/API: `CONCLAVE_WORKSPACE_UI_READ_LIMIT_BYTES`, Schreiben: `CONCLAVE_WORKSPACE_WRITE_LIMIT_BYTES`
- **Test:** `tests/api/test_workspace_api.py`

## 5. Workspace-Info im System-Prompt

- **Datei:** `infrastructure/system_prompt.py:build_workspace_info()`
- **Inhalt:** Anleitung für @workspace (lesen), @read (Agent liest), @save (Agent schreibt)
- **Datei-Listing:** Standardmäßig AUS. Nur mit gesetztem `CONCLAVE_WORKSPACE_AUTOLIST` wird zusätzlich eine Liste aller nicht versteckten Workspace-Dateien angehängt.
- **Trigger:** Bei jedem Provider-Call (in `assemble_system_prompt`), sofern das Workspace-Verzeichnis existiert
- **Scope:** Alle Adapter (Preset-Agents und native Anthropic-/OpenAI-Adapter)

## 6. context_files — Kontextdateien aus den Chat-Regeln

- **Datei:** `infrastructure/system_prompt.py:collect_context_files()`
- **Trigger:** Eine Zeile in den Chat-Regeln der Conversation, z. B. `context_files: a.md, b.md` (kommasepariert, Workspace-relative Pfade)
- **Aktion:** Der Inhalt jeder Datei wird als `--- Kontext: <pfad> ---` in den System-Prompt eingefügt; die `context_files:`-Zeile selbst erscheint nicht in den Chat-Regeln des Prompts
- **Security:** Gleiche Grenzen wie `@workspace`/`@read`: `resolve_workspace_path()` (kein absoluter Pfad, kein Ausbruch aus dem Workspace), `is_agent_visible()` (keine versteckten Pfade)
- **Limits:** `CONCLAVE_WORKSPACE_AGENT_READ_LIMIT_BYTES`, Default `524288`
- **Fehler:** Abgelehnte oder fehlende Einträge werden übersprungen und als Warnung geloggt
- **Scope:** Alle Adapter (Preset-Agents und native Anthropic-/OpenAI-Adapter)

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
_process_agent_directives_for_context() → Dateiinhalt eingefügt
                         → tool_events-Eintrag gespeichert
                         → Message referenziert [tool_event:<event_id>]
                         → gespeichert in DB
        |
Agent antwortet mit @save(ergebnis.md)\n...\n@endsave
        |
        v
_process_agent_directives_for_context() → Datei in workspace/output/ geschrieben
                         → tool_events-Eintrag gespeichert
                         → Message referenziert [tool_event:<event_id>]
```

**Code-Referenzen:**
- Lesen/Expandieren: `src/conclave/application/conversation_flow.py:_expand_workspace_refs()`
- Agent-Direktiven: `src/conclave/application/conversation_flow.py:_process_agent_directives_for_context()`
- Tool-Events: `src/conclave/domain/tool_event.py`, `src/conclave/infrastructure/sqlite/tool_event_repository.py`
- Tool-Event-API und Export: `GET /conversations/<id>/tool-events`,
  `GET /conversations/<id>/export`
- Security: `src/conclave/application/workspace_security.py`
- API: `src/conclave/api/app.py` Workspace-Endpunkte
- System-Prompt: `src/conclave/infrastructure/system_prompt.py:build_workspace_info()`,
  `collect_context_files()`, `assemble_system_prompt()`
- Tests: `tests/application/test_workspace_directives.py`, `tests/api/test_workspace_api.py`

**Zuletzt verifiziert:** 2026-10-26 (v0.2.0)
