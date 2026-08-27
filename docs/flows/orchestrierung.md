# Flow: Orchestrierung - Sequentiell, Parallel, Auto-Loop

**Auslöser:** POST /conversations/{id}/orchestrate, /orchestrate-parallel, /orchestrate-parallel-stream, /auto-loop

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
   - `response` — group, slot, participant, content, sequence, message_id, tool_events
   - `error` — group, slot, participant, message, type, status
   - `stop` — reason: "error"
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
   - `rotation`: "none" oder "round_robin"
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
   - `response` — round, participant, round_sequence, content (nach dem Call)
   - `stop` — reason: "signal" | "max_rounds" | "error"
10. SSE-Stream: `data: {json}\n\n` pro Event, `data: [DONE]\n\n` am Ende.

Der Loop ist kein Wahrheitsprüfer. Er automatisiert nur wiederholte Agentenaufrufe.
Der Mensch entscheidet, ob die Antworten brauchbar sind.

**Test:** `tests/api/test_auto_loop.py` (19 Tests)

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
- Parallel Live: Sendet fertige Antworten weiter, markiert Fehler und stoppt
  nach Abschluss der laufenden Gruppe
- Auto-Loop: stop-Event mit reason "error", SSE-Stream wird sauber beendet

**Code-Referenzen:**
- `src/conclave/application/orchestrator.py` — Orchestrator + ParallelOrchestrator
- `src/conclave/cli/handler.py:orchestrate_parallel_stream()` — Generator
- `src/conclave/cli/handler.py:auto_loop()` — Generator
- `src/conclave/api/app.py` — 3 Endpoints

**Zuletzt verifiziert:** 2026-08-11 im Personal-Multiplattform-Schnitt
