# Flow: Orchestrierung - Sequentiell, Parallel, Auto-Loop

**Auslöser:** POST /conversations/{id}/orchestrate, /orchestrate-parallel, /orchestrate-parallel-stream, /auto-loop

**Vorbedingung:** Conversation existiert, Participants registriert, Agents mit Adaptern

## Sequentiell (POST /orchestrate)

1. `api/app.py:orchestrate()` liest `sequence` (Liste von Participant-IDs) aus Body.
2. `cli/handler.py:orchestrate()` erstellt `Orchestrator(service)`.
3. `application/orchestrator.py:Orchestrator.run(conversation_id, sequence)` iteriert über Participants.
4. Pro Participant: `service.invoke_participant()` — jeder sieht die Antworten aller Vorgänger.
5. Bei `ConversationNotFound`, `AdapterNotFound` oder `EmptyConversation`: Loop stoppt, Partial Result zurück (`OrchestratorResult` mit `error`, `error_type`, `status`; `EmptyConversation` → 400, `ConversationNotFound` → 404, `AdapterNotFound` → 502). Andere Fehler (z. B. `ParticipantNotRegistered`, Provider-Fehler) werden nicht abgefangen und enden als HTTP-Fehler über die Error-Handler in `api/app.py`. Bereits gespeicherte Antworten bleiben in beiden Fällen in der Conversation.
6. Ergebnis: `OrchestratorResult(success, responses=[ParticipantResponse(...)])`. Die API liefert bei `success=False` nur den Fehler (`error`, `type`) mit dem Status aus dem Ergebnis, nicht die Teilantworten.

**Test:** `tests/application/test_orchestrator.py`

## Parallel (POST /orchestrate-parallel)

1. `api/app.py:orchestrate_parallel()` liest `groups` (Liste von Listen) aus Body.
2. `cli/handler.py:orchestrate_parallel()` erstellt `ParallelOrchestrator(service)`.
3. `orchestrator.py:ParallelOrchestrator.run(conversation_id, groups)` — async.
4. Pro Gruppe: `asyncio.gather()` ruft alle Participants gleichzeitig über `service.async_complete_participant()` auf; synchrone Adapter laufen dabei per `asyncio.to_thread()` in Worker-Threads.
5. Innerhalb einer Gruppe sieht kein Agent die Antwort der anderen (gleicher Snapshot).
6. Gruppen untereinander sind sequentiell — spätere Gruppen sehen frühere Antworten.
7. Bei Exception in einem Agent: Die erfolgreichen Antworten derselben Gruppe werden trotzdem gespeichert, danach stoppt der Loop (keine weiteren Gruppen); bisherige Responses + Fehlermeldung zurück (`EmptyConversation` → Status 400, unbekannte Conversation → 404, sonst 502).

**Test:** `tests/application/test_parallel_orchestrator.py`

## Parallel Live (POST /orchestrate-parallel-stream)

1. `api/app.py:orchestrate_parallel_stream()` liest `groups` und gibt
   `text/event-stream` zurück.
2. `cli/handler.py:orchestrate_parallel_stream()` ist ein Generator und
   liefert SSE-fähige Events.
3. Innerhalb einer Gruppe werden alle Participants parallel gestartet.
4. Sobald ein Participant fertig ist, wird seine Antwort sofort als Message
   gespeichert und als `response`-Event gesendet.
5. Die UI zeigt beim Start Platzhalter pro Agent und ersetzt jeden Platzhalter,
   sobald die passende Antwort eintrifft.
6. Antworten erscheinen in Fertigstellungsreihenfolge, nicht zwingend in der
   eingegebenen Agentenreihenfolge.
7. Gruppen bleiben sequentiell: Spätere Gruppen sehen die gespeicherten
   Antworten früherer Gruppen.
8. Events:
   - `start` — groups, total
   - `group_start` — group, participants
   - `invoke` — group, slot, participant
   - `response` — group, slot, participant, participant_id, content, sequence, message_id, tool_events
   - `error` — group, slot, participant, message, type, status
   - `group_done` — group, responses (Anzahl bisher gespeicherter Antworten)
   - `stop` — reason: "error", message, type, status, responses. Ist die
     Conversation beim Laden einer Gruppe nicht (mehr) vorhanden, kommt `stop`
     ohne `responses` und mit `type: "ConversationNotFound"`, `status: 404`.
     Bei einer unerwarteten Exception sendet die API ein `stop` nur mit
     reason und message.
   - `done` — responses

**Test:** `tests/cli/test_handler_parallel.py`,
`tests/api/test_orchestrate_parallel_api.py`,
`tests/ui/test_personal_ui_surface.py`

## Auto-Loop (POST /auto-loop)

1. `api/app.py:auto_loop()` liest `sequence`, `stop_signal` (Default: "@done"), `max_rounds` (Default: 20) und `rotation` (Default: "none").
2. Die Eingaben werden vor Stream-Start normalisiert:
   - `sequence`: nicht-leere Liste von Participant-IDs
   - maximal 20 Participant-Aufrufe pro Runde
   - leere IDs und Nicht-Strings werden abgelehnt
   - `stop_signal`: nicht leer, maximal 128 Zeichen
   - `max_rounds`: ganze Zahl zwischen 1 und 50
   - `rotation`: "none" oder "round_robin" ("round-robin" und Groß-/Kleinschreibung werden normalisiert)
3. `cli/handler.py:auto_loop()` ist ein **Generator** — liefert SSE-Events.
4. Pro Runde wird eine `round_sequence` berechnet.
   - `none`: jede Runde nutzt exakt `sequence`
   - `round_robin`: Runde 1 `a,b,c`, Runde 2 `b,c,a`, Runde 3 `c,a,b`
5. Pro Runde: Alle Participants in `round_sequence` werden sequentiell aufgerufen.
6. Jeder `invoke_participant()` schreibt die Modellantwort als normale Conversation-Message.
7. Dadurch sieht der nächste Agent alle vorherigen Antworten aus demselben Loop.
8. Nach jeder Antwort: Prüfung ob `stop_signal` (case-insensitiv) im Content enthalten.
9. Events:
   - `start` — max_rounds, sequence, stop_signal, rotation
   - `invoke` — round, participant, round_sequence (vor dem Call)
   - `response` — round, participant, round_sequence, content, message_id, tool_events (nach dem Call)
   - `stop` — reason und je nach Grund:
     - "signal": signal, participant, round
     - "max_rounds": rounds
     - "error": participant, round, message (bei unerwarteter Exception nur message)
10. SSE-Stream: `data: {json}\n\n` pro Event, `data: [DONE]\n\n` am Ende.

Der Loop ist kein Wahrheitsprüfer. Er automatisiert nur wiederholte Agentenaufrufe.
Der Mensch entscheidet, ob die Antworten brauchbar sind.

**Test:** `tests/api/test_auto_loop.py`

## Datenfluss

```
API-Request
    |
    v
CLIHandler.orchestrate/orchestrate_parallel/orchestrate_parallel_stream/auto_loop
    |
    v
Orchestrator.run / ParallelOrchestrator.run / Generator
    |
    v
ConversationFlowService.invoke_participant (sequentiell, Auto-Loop)
bzw. async_complete_participant + asyncio.to_thread (parallel)
    |
    v
Workspace-Refs -> AdapterRegistry -> ResilientAdapter -> Provider
    |
    v
MessageRepository + RunRepository + AuditRepository
```

**Fehlerfall:**
- Sequentiell: Stoppt bei erstem Fehler; Partial Result nur bei
  `ConversationNotFound`, `AdapterNotFound`, `EmptyConversation`, sonst HTTP-Fehler
- Parallel: Speichert die erfolgreichen Antworten der Gruppe und stoppt dann
- Parallel Live: Sendet fertige Antworten weiter, markiert Fehler und stoppt
  nach Abschluss der laufenden Gruppe
- Auto-Loop: stop-Event mit reason "error", SSE-Stream wird sauber beendet

**Code-Referenzen:**
- `src/conclave/application/orchestrator.py` — Orchestrator + ParallelOrchestrator
- `src/conclave/cli/handler.py:orchestrate_parallel_stream()` — Generator
- `src/conclave/cli/handler.py:auto_loop()` — Generator
- `src/conclave/api/app.py` — 4 Endpoints (orchestrate, orchestrate-parallel, orchestrate-parallel-stream, auto-loop)

**Zuletzt verifiziert:** 2026-10-26 (v0.2.0)
