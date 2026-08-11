# Flow: API-Request - Vom HTTP-Call zur LLM-Antwort

**Ausloeser:** POST /conversations/{id}/participants/{pid}/invoke

**Vorbedingung:** Conversation existiert, Participant ist registriert, Agent hat
einen passenden Adapter.

**Schritte:**

1. **Authentifizierung** — `api/app.py:_authenticate()` prueft Bearer-Token oder X-API-Key. Bei RoleBasedAuthService zusaetzlich `check_permission()`.

2. **Request-Routing** — `api/app.py:invoke_participant()` liest conversation_id und participant_id aus der URL.

3. **Handler-Delegation** — `cli/handler.py:invoke_participant()` ruft den `ConversationFlowService` auf.

4. **Conversation laden** — `application/conversation_flow.py:load_conversation()` laedt Conversation, Participants und Messages aus den lokalen Repositories.

5. **Participant validieren** — `conversation_flow.py:invoke_participant()` sucht den Participant in der Conversation und bricht bei unbekannten Participants ab.

6. **Adapter holen** — `adapter_registry.py:get_for(participant_id)` liefert den registrierten Adapter oder baut ihn ueber den Lazy Builder aus der lokalen Agent-Konfiguration.

7. **Workspace-Refs expandieren** — `conversation_flow.py:_expand_workspace_refs()` ersetzt `@workspace/datei` und `@read(...)` durch erlaubte lokale Datei-Inhalte.

8. **Messages formatieren** — der jeweilige Adapter formatiert Conversation, Rollen und Modellparameter fuer den Provider.

9. **System-Prompt bauen** — Agent-Rolle, Conversation-Regeln und Workspace-Kontext werden in den Provider-Call einbezogen.

10. **Provider-Call** — `ResilientAdapter.complete()` -> `UniversalAdapter.complete()` -> `ProviderProfile.build_body/headers/url()` -> HTTP-Call. Retry bei 429/5xx.

11. **Response extrahieren** — `ProviderProfile.extract_response()` liest die Antwort provider-spezifisch, zum Beispiel OpenAI Responses, Anthropic, Gemini oder kompatible Endpunkte.

12. **Agent-Direktiven verarbeiten** — `conversation_flow.py:_process_agent_directives()` schreibt `@save(...)`-Bloecke in den Workspace und ersetzt sie in der Antwort durch einen Workspace-Link.

13. **Message persistieren** — `MessageRepository.save()` — Sequence atomar aus DB (MAX+1).

14. **Run und Usage persistieren** — `conversation_flow.py:_record_run()` speichert Status, Participant, Provider, Modell, Dauer, Fehler und optionale Usage.

15. **Audit-Log** — `conversation_flow.py:_audit()` ergaenzt den technischen Verlauf fuer Usage-Auswertungen.

**Fehlerfall:**
- AuthenticationError → 401
- ConversationNotFound → 404
- AdapterNotFound → 502
- ProviderRateLimit → 429 (nach Retry-Exhaustion)
- ProviderTimeout → 504
- ProviderUnavailable → 502

**Code-Referenzen:**
- Einstiegspunkt: `src/conclave/api/app.py:invoke_participant()`
- Kernlogik: `src/conclave/application/conversation_flow.py:invoke_participant()`
- Adapter: `src/conclave/infrastructure/universal/adapter.py:UniversalAdapter.complete()`
- Tests: `tests/application/test_invoke_participant.py`, `tests/application/test_personal_golden_path.py`

**Zuletzt verifiziert:** 2026-08-11 im Personal-Multiplattform-Schnitt
