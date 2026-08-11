# Flow: Orchestrierung - Sequentiell, Parallel, Auto-Loop

**Auslöser:** POST /conversations/{id}/orchestrate, /orchestrate-parallel, /auto-loop

**Vorbedingung:** Conversation existiert, Participants registriert, Agents mit Adaptern

## Sequentiell (POST /orchestrate)

1. `api/app.py:orchestrate()` liest `sequence` (Liste von Participant-IDs) aus Body.
2. `cli/handler.py:orchestrate()` erstellt `Orchestrator(service)`.
3. `application/orchestrator.py:Orchestrator.run(conversation_id, sequence)` iteriert über Participants.
4. Pro Participant: `service.invoke_participant()` — jeder sieht die Antworten aller Vorgänger.
5. Bei `ConversationNotFound` oder `AdapterNotFound`: Loop stoppt, Partial Result zurück.
6. Ergebnis: `OrchestratorResult(success, responses=[ParticipantResponse(...)])`.

**Test:** `tests/application/test_orchestrator.py`

## Parallel (POST /orchestrate-parallel)

1. `api/app.py:orchestrate_parallel()` liest `groups` (Liste von Listen) aus Body.
2. `cli/handler.py:orchestrate_parallel()` erstellt `ParallelOrchestrator(service)`.
3. `orchestrator.py:ParallelOrchestrator.run(conversation_id, groups)` — async.
4. Pro Gruppe: `asyncio.gather()` ruft alle Participants gleichzeitig auf.
5. Innerhalb einer Gruppe sieht kein Agent die Antwort der anderen (gleicher Snapshot).
6. Gruppen untereinander sind sequentiell — spätere Gruppen sehen frühere Antworten.
7. Bei Exception in einem Agent: Loop stoppt, bisherige Responses + Fehlermeldung zurück.

**Test:** `tests/application/test_parallel_orchestrator.py`

## Auto-Loop (POST /auto-loop)

1. `api/app.py:auto_loop()` liest `sequence`, `stop_signal` (Default: "@done"), `max_rounds` (Default: 20).
2. `cli/handler.py:auto_loop()` ist ein **Generator** — liefert SSE-Events.
3. Pro Runde: Alle Participants in `sequence` werden sequentiell aufgerufen.
4. Nach jeder Antwort: Prüfung ob `stop_signal` (case-insensitiv) im Content enthalten.
5. Events:
   - `start` — max_rounds, sequence, stop_signal
   - `invoke` — round, participant (vor dem Call)
   - `response` — round, participant, content (nach dem Call)
   - `stop` — reason: "signal" | "max_rounds" | "error"
6. SSE-Stream: `data: {json}\n\n` pro Event, `data: [DONE]\n\n` am Ende.

**Test:** `tests/api/test_auto_loop.py` (19 Tests)

## Datenfluss

```
API-Request
    |
    v
CLIHandler.orchestrate/orchestrate_parallel/auto_loop
    |
    v
Orchestrator.run / ParallelOrchestrator.run / Generator
    |
    v
ConversationFlowService.invoke_participant (pro Agent)
    |
    v
Workspace-Refs -> AdapterRegistry -> ResilientAdapter -> Provider
    |
    v
MessageRepository + RunRepository + AuditRepository
```

**Fehlerfall:**
- Sequentiell: Stoppt bei erstem Fehler, Partial Result
- Parallel: Stoppt bei erstem Fehler in einer Gruppe
- Auto-Loop: stop-Event mit reason "error", SSE-Stream wird sauber beendet

**Code-Referenzen:**
- `src/conclave/application/orchestrator.py` — Orchestrator + ParallelOrchestrator
- `src/conclave/cli/handler.py:auto_loop()` — Generator
- `src/conclave/api/app.py` — 3 Endpoints

**Zuletzt verifiziert:** 2026-08-11 im Personal-Multiplattform-Schnitt
