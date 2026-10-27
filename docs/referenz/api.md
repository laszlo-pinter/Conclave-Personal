# API-Referenz

**54 dokumentierte Endpoints** — öffentliche Personal-API.

Alle Endpoints außer `GET /`, `/static/*`, `GET /health`, `GET /api-docs` und
`GET /openapi.json` verlangen ein Token (`Authorization: Bearer <token>` oder
`X-API-Key`). Ohne Token funktionieren außerdem `HEAD` auf diese öffentlichen
Pfade und `OPTIONS` (CORS-Preflight, `204`) auf allen Pfaden. POST-Anfragen
brauchen `Content-Type: application/json` (auch ohne Inhalt: `{}`) oder den
Header `X-Conclave-Client`, sonst `415`. Anfragen mit nicht erlaubtem
`Host`-Header werden mit `421` abgelehnt. Details: [Sicherheit](../sicherheit.md).

| Methode | Pfad | Beschreibung |
|---------|------|-------------|
| `GET` | `/` | Serve Ui |
| `GET` | `/api-docs` | Swagger UI — interaktive API-Dokumentation (lokal ausgeliefert, keine CDN-Ressourcen). |
| `GET` | `/openapi.json` | OpenAPI 3.0 Spec als JSON. |
| `GET` | `/health` | Healthcheck für lokale Runtime und Integrationen. |
| `POST` | `/conversations` | Create Conversation |
| `GET` | `/conversations` | List Conversations |
| `GET` | `/agents` | List Agents |
| `GET` | `/agents/<agent_id>` | Get Agent |
| `POST` | `/agents` | Create Agent |
| `PUT` | `/agents/<agent_id>` | Update Agent |
| `DELETE` | `/agents/<agent_id>` | Delete Agent |
| `GET` | `/presets` | List Presets |
| `GET` | `/agent-roles` | List Agent Roles |
| `GET` | `/providers` | Listet verfügbare Provider-Presets ohne Secrets. |
| `POST` | `/agents/<agent_id>/test` | Test Agent |
| `DELETE` | `/conversations/<conversation_id>` | Delete Conversation |
| `POST` | `/conversations/<conversation_id>/topic` | Set Topic |
| `GET` | `/conversations/<conversation_id>/rules` | Get Rules |
| `POST` | `/conversations/<conversation_id>/rules` | Set Rules |
| `POST` | `/conversations/<conversation_id>/floor/grant` | Grant Floor |
| `POST` | `/conversations/<conversation_id>/floor/revoke` | Revoke Floor |
| `POST` | `/conversations/<conversation_id>/floor/invoke` | Invoke With Floor |
| `GET` | `/conversations/<conversation_id>` | Get Conversation |
| `GET` | `/conversations/<conversation_id>/messages/<message_id>/context` | Vollständiger Kontext-Report einer Modellantwort (siehe unten). |
| `GET` | `/conversations/<conversation_id>/participants/<participant_id>/context-preview` | Vorschau: welcher Kontext beim nächsten Aufruf gesendet würde, ohne Provider-Aufruf. |
| `GET` | `/conversations/<conversation_id>/tool-events` | List Tool Events |
| `POST` | `/consultations` | Zweitmeinung zu einem Kanzo-Ticket anfordern (`202`, siehe unten). |
| `GET` | `/consultations` | Consultations zu einem Ticket (`?source_ref=api#12`, URL-kodiert). |
| `GET` | `/consultations/<consultation_id>` | Status, Reviewer mit Provider, Zustellungen. |
| `POST` | `/consultations/<consultation_id>/retry` | Offene Zustellungen erneut; `rerun: true` ruft die Modelle erneut auf. |
| `POST` | `/conversations/<conversation_id>/participants` | Add Participant |
| `DELETE` | `/conversations/<conversation_id>/participants/<participant_id>` | Delete Participant |
| `POST` | `/conversations/<conversation_id>/messages` | Add Message |
| `POST` | `/conversations/<conversation_id>/participants/<participant_id>/invoke` | Invoke Participant |
| `POST` | `/conversations/<conversation_id>/orchestrate` | Orchestrate |
| `POST` | `/conversations/<conversation_id>/orchestrate-parallel` | Orchestrate Parallel |
| `POST` | `/conversations/<conversation_id>/orchestrate-parallel-stream` | Orchestrate Parallel Stream |
| `GET` | `/conversations/<conversation_id>/participants/<participant_id>/stream` | Stream Participant |
| `POST` | `/conversations/<conversation_id>/auto-loop` | Auto Loop |
| `GET` | `/conversations/<conversation_id>/export` | Export Conversation |
| `GET` | `/usage` | Token Usage |
| `GET` | `/usage/conversations` | Conversation Usage |
| `GET` | `/runs` | List Runs |
| `GET` | `/runs/<run_id>` | Get Run |
| `GET` | `/settings` | Gibt lokale Runtime-Settings ohne Secrets zurück. |
| `PUT` | `/settings` | Aktualisiert Runtime-Settings: `workspace_path` nur für die laufende Session, `rate_limit` siehe unten. |
| `POST` | `/backup` | Erstellt ein lokales ZIP-Backup von SQLite-DB und Workspace. |
| `GET` | `/logs` | Letzte Einträge der Server-Logdatei (`limit` bis 1000, `level` DEBUG…CRITICAL). |
| `GET` | `/backups` | Listet die ZIP-Backups im Backup-Verzeichnis (neueste zuerst). |
| `POST` | `/restore` | Stellt SQLite-DB und Workspace aus einem ZIP-Backup im Backup-Verzeichnis wieder her. |
| `GET` | `/workspace` | Listet alle Dateien im Workspace. |
| `GET` | `/workspace/<path:filepath>` | Liest eine Datei aus dem Workspace. |
| `POST` | `/workspace/<path:filepath>` | Schreibt eine Datei in den Workspace. |
| `DELETE` | `/workspace/<path:filepath>` | Löscht eine Datei aus dem Workspace. |

*Stand: v0.2.0 (2026-10-26), abgeglichen mit `openapi.json`*

## Kontext-Reports

Zu jedem Modellaufruf speichert Conclave, welcher Kontext an den Provider ging.
Gespeichert werden nur Metadaten (Anzahlen, Sequenznummern, Dateipfade und
-größen), nie der Prompt selbst. Auch fehlgeschlagene Aufrufe bekommen einen
Report, verknüpft mit dem Run, aber ohne Nachricht. Dasselbe Bild entsteht bei
paralleler Orchestrierung, wenn eine Antwort zwar erzeugt, aber nicht mehr
gespeichert werden konnte (der Report wird vor dem Speichern angelegt). Das ist
kein Datenfehler.

- `GET /conversations/<id>` und die Antworten von Invoke, Orchestrierung,
  Parallel-Stream (`response`-Events) und Auto-Loop (`response`-Events)
  enthalten pro Modellantwort ein kompaktes `context`-Objekt (`null` bei
  User-Nachrichten und älteren Antworten):
  `messages_sent`, `messages_total`, `truncated`, `omitted_sequences`,
  `files` (`context_files` plus per `@workspace/` eingefügte Dateien),
  `read_results` (frühere `@read()`-Ergebnisse im gesendeten Verlauf),
  `skipped_files`, `estimated_tokens` (Schätzung, ca. 3,5 Zeichen pro Token),
  `billed_input_tokens`/`billed_output_tokens` (vom Provider abgerechnet,
  `null` wenn nicht gemeldet), `adapter`, `attempts`.
- `GET /conversations/<id>/messages/<message_id>/context` liefert den
  vollständigen Report (`report`, `usage`, `run_id`). `404`, wenn Conversation,
  Nachricht oder Report fehlen (`type`: `ConversationNotFound`,
  `MessageNotFound`, `ContextReportNotFound`).
- `GET /conversations/<id>/participants/<pid>/context-preview` berechnet den
  Report für den nächsten Aufruf, ohne den Provider aufzurufen und ohne etwas zu
  speichern. `404` bei unbekannter Conversation, unbekanntem Participant oder
  fehlendem Adapter; `409` (`PreviewUnavailable`), wenn der Adapter keine
  Vorschau anbietet.
- Der Einzel-Stream (`.../stream`) liefert weiterhin nur Text-Tokens; den
  Report enthält danach `GET /conversations/<id>`.
- Der Export (`GET /conversations/<id>/export`) enthält alle Reports unter
  `context_reports`.

## Consultations

Eine Consultation holt eine Zweitmeinung mehrerer Reviewer-Modelle zu einem
Ticket aus [Kanzo](https://github.com/emanuele-em/kanzo) und schreibt jede
Antwort als Kommentar in das Ticket. Voraussetzung: `[kanzo]` in
`config.toml` mit `reviewers` (siehe [Konfiguration](konfiguration.md#consultations-kanzo));
ohne Reviewer-Liste antworten die Endpunkte mit `503`
(`ConsultationsDisabled`). Sicherheit: [Sicherheit](../sicherheit.md#consultations-kanzo).

`POST /consultations`:

```json
{"task": "api#12", "question": "Ist der Fix richtig?",
 "context": "optional", "reviewers": ["gpt"], "include_previous": false}
```

- `task` (Pflicht): Ticket-Referenz `projekt#nummer` (Kleinbuchstaben).
- `question` (Pflicht, bis 4.000 Zeichen), `context` (optional, bis 8.000).
- `reviewers`: Teilmenge von `[kanzo] reviewers`; Standard: alle erlaubten.
- `include_previous`: frühere Conclave-Kommentare des Tickets mitgeben
  (Standard `false`; dann als „frühere Modellausgabe“ gekennzeichnet).
- `channel`: `rest` (Standard) oder `mcp`; das MCP-Tool setzt immer `mcp`.
- Antwort `202` mit `id`, `status: "queued"` und `reviewers` (je Reviewer
  Provider und Modell: an diese Provider geht der Ticket-Inhalt).

Fehler: `400` (`ValidationError`, `ReviewerNotAllowed`), `403`
(`HumanOnlyTicket`: Ticket nur für Menschen, Anfrage über `mcp`), `404`
(Ticket unbekannt), `429` (`ConsultationLimit`: `[kanzo] max_per_hour` pro
Ticket und Stunde erreicht), `502` (Kanzo nicht erreichbar oder unbekanntes
Ausgabeformat), `503` (nicht eingerichtet). Bei diesen Fehlern wird nichts
gespeichert.

Ablauf im Hintergrund: Conclave legt die Conversation
`kanzo:<task> · <id>` an, fragt alle Reviewer parallel und stellt jede Antwort
als Kommentar zu. Status: `queued` → `running` → `done` | `failed`; nach einem
Server-Neustart wird `running` zu `interrupted`. Jeder Kommentar endet mit einer
Schlusszeile wie

`— Zweitmeinung von GPT (openai, gpt-5.6) über Conclave, nicht geprüft · consultation <id>/gpt`

Lange Antworten werden vorher auf `[kanzo] comment_max_chars` gekürzt (mit
Verweis auf die Conversation); die Schlusszeile bleibt immer erhalten.

`GET /consultations/<id>` liefert zusätzlich `deliveries` (je Reviewer
`status` `pending`/`delivered`/`failed`, `attempts`, `error`, `marker`) und
`retry_possible`.

`POST /consultations/<id>/retry`:

- ohne Body bzw. `{"rerun": false}`: offene oder fehlgeschlagene Zustellungen
  gespeicherter Antworten erneut zustellen, **ohne** Modellaufrufe. Gibt es
  keine gespeicherte Antwort: `409` (`NothingToDeliver`).
- `{"rerun": true}`: legt eine neue Consultation mit denselben Angaben an
  (ruft die Modelle erneut auf, zählt zur Obergrenze).
- Läuft die Consultation noch: `409` (`ConsultationBusy`).

Nach einem Neustart stellt Conclave gespeicherte, aber nicht zugestellte
Antworten automatisch zu. Modelle werden nie automatisch erneut aufgerufen.

## Backup und Restore

- `POST /backup` legt ein ZIP im Backup-Verzeichnis an und liefert dessen
  Namen in `backup`. Backup-Verzeichnis: `CONCLAVE_BACKUP_DIR`, sonst bei
  SQLite `backups/` neben der Datenbank, bei PostgreSQL
  `<Elternordner des Workspace>/backups`. (Die CLI `conclave backup` ohne
  `--dir` nutzt dagegen `CONCLAVE_BACKUP_DIR`, sonst immer
  `<Elternordner des Workspace>/backups`.)
- `GET /backups` listet die vorhandenen Backups (`name`, `size_bytes`,
  `modified_at`).
- `POST /restore` akzeptiert nur einen Dateinamen aus dieser Liste:
  `{"backup": "conclave-backup-20261026T120000Z.zip"}`. Pfade, `..`,
  Laufwerksangaben und Symlinks aus dem Verzeichnis heraus werden mit `400`
  abgelehnt; das frühere Feld `backup_path` wird nicht mehr unterstützt.
- Standardmäßig bleibt der Workspace erhalten; Dateien aus dem Backup werden
  hinzugefügt bzw. überschrieben. Den Workspace vorher leeren nur mit
  `"replace_workspace": true` **und** `"confirm": "replace-workspace"`.
- Vor jedem Restore wird automatisch ein `conclave-pre-restore-*.zip` angelegt.
- Die CLI (`conclave restore --backup <pfad>`) darf weiterhin beliebige Pfade
  verwenden.

## Agent-Keys

- `PUT /agents/<agent_id>` ohne `api_key` (oder mit leerem Wert) behält den
  gespeicherten Key. Gespeicherte Keys werden nie ausgeliefert, daher schickt
  die UI beim Bearbeiten nur einen neu eingegebenen Key mit.
- Ein neuer `api_key` ersetzt den gespeicherten.
- Entfernen nur ausdrücklich mit `"clear_api_key": true`.

## Settings: Rate-Limit

- `GET /settings` liefert unter `rate_limit` den aktuellen Wert, die Herkunft
  (`default`, `config`, `env`, `session`), ob es aktiv ist, ob es änderbar ist
  und ob Änderungen in `config.toml` gespeichert werden.
- `PUT /settings` mit `{"rate_limit": "300 per minute"}` (oder `"off"`) wirkt
  sofort. Ist ein Config-Pfad bekannt (`persistent: true`), wird der Wert in
  `[server] rate_limit` der `config.toml` gespeichert, sonst gilt er nur für
  die laufende Session (Herkunft `session`).
  Ungültige oder leere Werte → `400`; ist `CONCLAVE_RATE_LIMIT` gesetzt → `409`.
- `workspace_path` in `PUT /settings` gilt nur für die laufende Session und
  wird nicht gespeichert.

## Fehlercodes

Fehler kommen als JSON `{"error": "...", "type": "..."}`. Wichtige Codes:

- `400` — ungültige Eingaben, leere Conversation, Provider-Client-Fehler (4xx)
- `401` — Token fehlt oder ist falsch
- `404` — Conversation, Participant, Agent, Run oder Datei nicht gefunden
  (auch Invoke in einer unbekannten Conversation)
- `409` — Konflikt (z. B. Agent/Participant existiert bereits, kein Rederecht,
  Rate-Limit durch `CONCLAVE_RATE_LIMIT` gesperrt)
- `415` — POST ohne JSON bzw. `X-Conclave-Client`; Binärdatei im Workspace
- `421` — `Host`-Header nicht erlaubt
- `429` — eigenes Rate-Limit überschritten (`RateLimitExceeded`) oder
  Provider-Rate-Limit nach ausgeschöpften Retries (`ProviderRateLimit`)
- `502` — Provider-Fehler (`ProviderUnavailable` u. a.), kein Adapter
  (`AdapterNotFound`)
- `504` — Provider-Timeout (`ProviderTimeout`)
