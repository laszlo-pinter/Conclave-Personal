# Flow: API-Request - Vom HTTP-Call zur LLM-Antwort

**Auslöser:** POST /conversations/{id}/participants/{pid}/invoke

**Vorbedingung:** Conversation existiert und enthält mindestens eine Message,
Participant ist registriert, Agent hat einen passenden Adapter.

**Schritte:**

1. **Prüfungen** — `api/app.py:_check_host()` prüft den `Host`-Header, `_check_csrf()` verlangt bei POST JSON oder `X-Conclave-Client`, `_authenticate()` prüft Bearer-Token oder X-API-Key.

2. **Request-Routing** — `api/app.py:invoke_participant()` liest conversation_id und participant_id aus der URL.

3. **Handler-Delegation** — `cli/handler.py:invoke_participant()` ruft den `ConversationFlowService` auf und übersetzt `ConversationNotFound` (404), `AdapterNotFound` (502) und `EmptyConversation` (400) in ein Fehlerergebnis.

4. **Conversation laden** — `application/conversation_flow.py:load_conversation()` lädt Conversation, Participants und Messages aus den lokalen Repositories.

5. **Participant validieren** — `conversation_flow.py:invoke_participant()` sucht den Participant in der Conversation und wirft bei unbekannten Participants `ParticipantNotRegistered`.

6. **Adapter holen** — `adapter_registry.py:get_for(participant_id)` liefert den registrierten Adapter oder baut ihn über den Lazy Builder (`cli/bootstrap.py:_build_adapter_for_agent()`) aus der lokalen Agent-Konfiguration.

7. **Nachrichten prüfen** — `_ensure_has_messages()` wirft `EmptyConversation`, wenn die Conversation noch keine Message hat.

8. **Workspace-Refs expandieren** — `conversation_flow.py:_expand_workspace_refs()` ersetzt `@workspace/datei` (auch `@workplace/datei`) in den Messages eines Snapshots durch erlaubte lokale Datei-Inhalte. `@read(...)` wird hier nicht verarbeitet, sondern erst nach der Modellantwort (Schritt 13).

9. **Messages auswählen und formatieren** — `domain/context_report.py:select_messages()` wählt die gesendeten Nachrichten (Agent-Limit `max_messages`, sonst `CONCLAVE_MAX_MESSAGES` für Preset-Agents; native Adapter ohne Limit senden alles); der jeweilige Adapter formatiert sie mit Rollen und Modellparametern für den Provider.

10. **System-Prompt bauen** — alle Adapter (UniversalAdapter und die nativen Anthropic-/OpenAI-Adapter) kombinieren System-Prompt des Agenten, Inhalte aus `context_files:`, Chat-Regeln und Workspace-Hinweise (`infrastructure/system_prompt.py:assemble_system_prompt()`). Das Agent-Feld `role` fließt in keinen Prompt ein.

11. **Provider-Call** — zwei Wege, beide in `ResilientAdapter` gekapselt:
    - Preset/Universal (Agent mit `preset` oder `api_url`): `ResilientAdapter.complete()` -> `UniversalAdapter.complete()` -> `ProviderProfile.build_body/headers/url()` -> HTTP-Call über httpx.
    - Nativ (Provider `anthropic` oder `openai` ohne `preset` und ohne `api_url`): `ResilientAdapter.complete()` -> `AnthropicAdapter`/`OpenAIAdapter` über das jeweilige SDK.

    `ResilientAdapter` wiederholt und mappt nur httpx-Fehler (429 -> `ProviderRateLimit`, 5xx -> `ProviderUnavailable`, Timeout -> `ProviderTimeout`); Fehler der nativen SDKs werden nicht gemappt.

12. **Response extrahieren** — beim UniversalAdapter liest `ProviderProfile.extract_response()` die Antwort provider-spezifisch, zum Beispiel OpenAI Responses, Anthropic, Gemini oder kompatible Endpunkte.

13. **Audit-Log** — `conversation_flow.py:_audit()` protokolliert den Aufruf mit Provider, Modell und Tokens (nur wenn ein AuditRepository gesetzt ist, z. B. im Server).

14. **Run und Usage persistieren** — `conversation_flow.py:_record_run()` speichert Status, Participant, Provider, Modell, Dauer und optionale Usage aus dem `Completion` des Adapters. Bei einem Fehler im Provider-Call werden Audit und Run mit Status `failed` geschrieben und der Fehler weitergereicht.

14a. **Kontext-Report speichern** — `conversation_flow.py:_save_context_report()` speichert den Report des Aufrufs mit Run und (nach Schritt 16) Message. Bei einem Fehler hängt der Adapter den Report an die Exception; er wird dann nur mit dem fehlgeschlagenen Run gespeichert.

15. **Agent-Direktiven verarbeiten** — `_store_model_response()` -> `_process_agent_response()` -> `_process_agent_directives_for_context()` schreibt `@save(...)`-Blöcke in `workspace/output/` und ersetzt `@read(...)` durch den Dateiinhalt. Ist ein ToolEventRepository gesetzt (Server und CLI immer), wird ein `@save`-Block durch `[tool_event:<id>]` ersetzt und vor einem `@read`-Inhalt `[tool_event:<id>]` eingefügt.

16. **Message persistieren** — `MessageRepository.save()` — Sequence atomar aus DB (MAX+1).

17. **Tool-Events speichern** — `_save_tool_events()` speichert die Tool-Events mit der `message_id` der neuen Message.

**Fehlerfall:**
- AuthenticationError → 401
- ConversationNotFound → 404
- ParticipantNotRegistered → 404
- AgentNotFound (kein Agent zur Participant-ID) → 404
- EmptyConversation → 400
- AdapterNotFound → 502
- Provider-Client-Fehler 4xx (UniversalAdapter, `ValueError`) → 400
- ProviderRateLimit → 429 (nach Retry-Exhaustion)
- ProviderTimeout → 504
- ProviderUnavailable → 502

**Code-Referenzen:**
- Einstiegspunkt: `src/conclave/api/app.py:invoke_participant()`
- Kernlogik: `src/conclave/application/conversation_flow.py:invoke_participant()`
- Adapter: `src/conclave/infrastructure/universal/adapter.py:UniversalAdapter.complete()`,
  `src/conclave/infrastructure/anthropic/adapter.py`, `src/conclave/infrastructure/openai/adapter.py`
- Adapter-Bau: `src/conclave/cli/bootstrap.py:_build_adapter_for_agent()`
- Fehler-Mapping: `src/conclave/api/app.py` (Error-Handler), `src/conclave/infrastructure/universal/resilient.py`
- Tests: `tests/application/test_invoke_participant.py`, `tests/application/test_personal_golden_path.py`

**Zuletzt verifiziert:** 2026-10-27 (v0.3.0)
