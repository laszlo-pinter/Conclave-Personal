# API-Referenz

Öffentliche Personal-API mit dem Board (die Tabelle unten nennt alle Routen).

Alle Endpoints außer `GET /`, `/static/*`, `GET /health`, `GET /api-docs`,
`GET /openapi.json`, `GET /board/versions` und der Board-Seite (`GET /ui/board`
samt `/ui/board/static/*`) verlangen ein Token (`Authorization: Bearer <token>` oder
`X-API-Key`). Ohne Token funktionieren außerdem `HEAD` auf diese öffentlichen
Pfade und `OPTIONS` (CORS-Preflight, `204`) auf allen Pfaden. POST-Anfragen
brauchen `Content-Type: application/json` (auch ohne Inhalt: `{}`) oder den
Header `X-Conclave-Client`, sonst `415`. Anfragen mit nicht erlaubtem
`Host`-Header werden mit `421` abgelehnt. Details: [Sicherheit](../sicherheit.md).

## Mensch- und Agent-Zugang

Das Token bestimmt die Rolle: Mensch-Token (`CONCLAVE_API_KEY`/`api.token`)
oder Agent-Token (`CONCLAVE_AGENT_KEY`/`agent.token`), dazu das Reviewer-Token
(`CONCLAVE_REVIEWER_KEY`/`reviewer.token`).
`GET /auth/whoami` liefert `{"role": "human"}`, `{"role": "agent"}` bzw.
`{"role": "reviewer"}`.

Mit dem Agent-Token sind nur die Routen erlaubt, die die MCP-Tools und
`conclave board wait` brauchen, dazu drei lesende Routen ohne Geheimnisse
(dieselben Daten liefern `GET /conversations/<id>` und der Export):

- `GET /auth/whoami`
- `GET /conversations/<id>/rules`, `GET /conversations/<id>/tool-events`,
  `GET /conversations/<id>/messages/<mid>/context`
- `GET`/`POST /conversations`, `GET /conversations/<id>`,
  `POST /conversations/<id>/topic`, `GET /conversations/<id>/export`
- `POST /conversations/<id>/participants` (nur `type: "model"`),
  `POST /conversations/<id>/messages`,
  `POST /conversations/<id>/participants/<pid>/invoke`,
  `POST /conversations/<id>/orchestrate`,
  `POST /conversations/<id>/orchestrate-parallel`
- `GET /agents`, `GET /usage`
- `GET /workspace`, `GET`/`POST /workspace/<path>`
- `POST /consultations`, `GET /consultations/<id>`
- Board (unter `/board/v1`, ebenso über den Alias `/board`): `GET`/`POST /board/v1/tasks`,
  `GET /board/v1/search`, `POST /board/v1/next`,
  `GET`/`PATCH /board/v1/projects/<slug>/tasks/<n>`,
  `POST /board/v1/projects/<slug>/tasks/<n>/comments`,
  `GET /board/v1/projects/<slug>/tasks/<n>/history`,
  `GET /board/v1/projects/<slug>/initiatives`,
  `GET /board/v1/projects/<slug>/initiatives/<vorhaben>/tasks/<n>`,
  `GET /board/v1/changes` (für `conclave board wait`; die feineren
  Regeln prüft das Board selbst, siehe [Board](#board))

Der Reviewer-Zugang (`reviewer.token`) hat eine engere Liste: `GET /auth/whoami`,
`GET /board/v1/tasks`, `GET /board/v1/changes`, `GET /board/v1/search`,
`GET /board/v1/projects/<slug>/tasks/<n>` samt `/history`,
`GET /board/v1/projects/<slug>/initiatives/<vorhaben>/tasks/<n>`, `POST .../comments` und als
einziger `POST /board/v1/projects/<slug>/tasks/<n>/review` und
`POST /board/v1/reviewer/heartbeat` (jeweils auch über den Alias `/board`).

Alles andere, auch jedes `DELETE` und neue Routen, ergibt `403`
`{"type": "HumanOnly", "error": "Nur für den Menschen-Zugang."}`.

| Methode | Pfad | Beschreibung |
|---------|------|-------------|
| `GET` | `/` | Serve Ui |
| `GET` | `/api-docs` | Swagger UI — interaktive API-Dokumentation (lokal ausgeliefert, keine CDN-Ressourcen). |
| `GET` | `/openapi.json` | OpenAPI 3.0 Spec als JSON. |
| `GET` | `/health` | Healthcheck für lokale Runtime und Integrationen. |
| `GET` | `/auth/whoami` | Rolle des anfragenden Tokens: `human`, `agent` oder `reviewer`. |
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
| `POST` | `/consultations` | Zweitmeinung zu einem Ticket anfordern (`202`, siehe unten). |
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
| `POST` | `/workspace/<path:filepath>` | Schreibt eine Datei in den Workspace (`content` als Text). Agenten: nur neue Dateien oder unter `agents/`, sonst `403`. |
| `DELETE` | `/workspace/<path:filepath>` | Löscht eine Datei aus dem Workspace. |
| `GET` | `/board/v1` | Spalten, Projekte, Änderungszähler und `reviewer` (Zustand wie `GET /board/v1/reviewer`; nur Mensch). |
| `GET` | `/board/v1/changes` | Änderungszähler; die UI, der Reviewer und `conclave board wait` laden neu, wenn er steigt (alle drei Zugänge). |
| `GET` | `/board/v1/reviewer` | Läuft der automatische Reviewer? `{"state": "active", "last_seen", "version", "task"}` oder `{"state": "off", "since"}` (nur Mensch). |
| `POST` | `/board/v1/reviewer/heartbeat` | Lebenszeichen des Reviewers, etwa alle 60 s: `version` (höchstens 50 Zeichen), `task` (laufendes Ticket oder `null`). Ohne Herzschlag seit 180 s gilt er als aus. Nur im Speicher des Servers (nur Reviewer-Zugang). |
| `POST` | `/board/v1/projects` | Projekt anlegen (nur Mensch). |
| `PUT` | `/board/v1/projects/<slug>` | Projekt umbenennen (nur Mensch). |
| `DELETE` | `/board/v1/projects/<slug>` | Projekt samt Tickets löschen (nur Mensch). Mit `only_empty=true` nur ein Projekt ohne Tickets (auch ohne erledigte) und ohne Vorhaben, sonst `409 ProjectNotEmpty`; Prüfung und Löschen in einem Schritt. So löscht die Board-Ansicht. |
| `GET` | `/board/v1/tasks` | Tickets in Board-Reihenfolge; Filter `project`, `status` (mehrfach), `include_done`. |
| `POST` | `/board/v1/tasks` | Ticket anlegen; neue Tickets landen in der ersten Spalte. Optional `initiative`: Kurzname eines vorhandenen Vorhabens. |
| `GET` | `/board/v1/search` | Suche in Titel, Tags, Beschreibung und Kommentaren (`q`, `project`, `include_done`). |
| `POST` | `/board/v1/next` | Oberstes freies Ticket der ersten Spalte übernehmen (atomar); `task` als `projekt#n` oder `projekt/vorhaben-n`. |
| `GET` | `/board/v1/projects/<slug>/tasks/<int:number>` | Ein Ticket mit Kommentaren; `can_approve` sagt, ob dieser Zugang im Projekt das Freigabe-Recht hat. |
| `PATCH` | `/board/v1/projects/<slug>/tasks/<int:number>` | Ticket ändern: `title`, `description`, `tags`, `status`, `human`, `index`, `rank`, optional `version`; `initiative` (Kurzname oder `null`) ordnet einem Vorhaben zu (nur Mensch); `assignee` (Text oder `null`) setzt die Zuständigkeit (Recht `assign:self`/`assign:other`, in Personal nur der Mensch). |
| `POST` | `/board/v1/projects/<slug>/tasks/<int:number>/release` | Hängendes Ticket freigeben: zurück in die erste Spalte, Zuständigkeit leer (nur Mensch). |
| `GET` | `/board/v1/stuck` | Übernommene Tickets, die länger als `minutes` (1 bis 525600, Standard 60) in Arbeit stehen, je mit `status_since`; optional `project` (nur Mensch). |
| `GET` | `/board/v1/projects/<slug>/initiatives` | Vorhaben des Projekts nach Rang. |
| `POST` | `/board/v1/projects/<slug>/initiatives` | Vorhaben anlegen: `slug`, `title`, optional `rank` (nur Mensch). |
| `PUT` | `/board/v1/projects/<slug>/initiatives/<initiative>` | Vorhaben umbenennen oder ranken: `title`, `rank` (nur Mensch). |
| `GET` | `/board/v1/projects/<slug>/initiatives/<initiative>/tasks/<int:number>` | Ein Ticket über seine Vorhaben-Nummer, Antwort wie oben. |
| `DELETE` | `/board/v1/projects/<slug>/tasks/<int:number>` | Ticket löschen (nur Mensch). |
| `GET` | `/board/v1/projects/<slug>/tasks/<int:number>/comments` | Kommentare mit Herkunft (nur Mensch; Agenten lesen sie über das Ticket). |
| `POST` | `/board/v1/projects/<slug>/tasks/<int:number>/comments` | Kommentar schreiben; die Herkunft kommt aus dem Token. |
| `GET` | `/board/v1/projects/<slug>/tasks/<int:number>/history` | Verlauf mit Herkunft: Anlegen und jede Änderung. |
| `POST` | `/board/v1/projects/<slug>/tasks/<int:number>/review` | Review-Status setzen (nur Reviewer-Zugang). |
| `POST` | `/board/v1/projects/<slug>/tasks/<int:number>/review/request` | Review neu anfordern: Status `requested`, das Ticket bleibt in `review` (nur Mensch, Freigabe-Recht). |
| `GET` | `/board/v1/projects/<slug>/history` | Projekt-Verlauf: Anlegen, Umbenennen, gelöschte Tickets (nur Mensch). |
| `PUT` | `/board/v1/comments/<comment_id>` | Eigenen Kommentar ändern (nur Mensch). |
| `DELETE` | `/board/v1/comments/<comment_id>` | Eigenen Kommentar löschen (nur Mensch). |
| `POST` | `/board/v1/import` | JSON-Export eines Kanzo-Boards übernehmen (nur Mensch, idempotent). |
| `GET` | `/board/versions` | Versionen der Board-API, ohne Token; dieselbe Angabe steht in `/health` unter `board_api`. |
| `GET` | `/ui/board` | Board-Seite (ohne Token ausgeliefert; sie meldet sich mit dem Token des Tabs an), Skripte und Stile unter `/ui/board/static/*`. |

### Versionierung der Board-API

Die Board-Routen liegen unter `/board/v1/...` (seit T3; Vertrag in
`packages/board/openapi/board-v1.json`). Die unversionierten Pfade `/board/...`
aus v0.7.0 bleiben als **Alias** mit denselben Antworten und Rechten. Jede Antwort
des Alias trägt `Deprecation`, `Sunset` (frühestens 1. März 2027) und
`Link: </board/v1/...>; rel="successor-version"`. UI und `conclave-mcp` nutzen v1.

Innerhalb von v1 gibt es nur Ergänzungen: neue Routen, neue optionale Felder in
Anfragen, neue Felder in Antworten. **Clients ignorieren unbekannte Felder.**
Brechend und damit nur in einer neuen Version (v2):

- Felder entfernen oder umbenennen, Typ oder Bedeutung ändern
- neue Pflichtfelder, strengere Prüfung
- andere Statuscodes oder Fehlerformate
- Rechte zum Nachteil bestehender Clients

v1 und eine neue Version laufen mindestens ein Minor-Release und drei Monate
parallel. Die CI vergleicht `board-v1.json` mit dem letzten Release-Stand
(`oasdiff breaking`); eine brechende Änderung lässt sie scheitern. Die Datei
entsteht mit `python scripts/gen-openapi.py` aus den registrierten Routen.

*Stand: v0.9.2 (Board-API v1, 2026-11-24), abgeglichen mit `openapi.json` und `board-v1.json`*

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
- Jede Nachricht hat `origin` (in `GET /conversations/<id>`, im Export und in
  der Antwort von `POST /conversations/<id>/messages`): `human` oder `agent`,
  je nach Token der Anfrage, nie aus dem Body. `null` heißt unbekannt
  (Modellantworten, ältere Nachrichten, Wege ohne Token wie die CLI).
  `author_type` bleibt für Nachrichten von Agenten `user`.
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
Ticket und schreibt jede Antwort als Kommentar in das Ticket. Die Tickets kommen
aus dem eigenen [Board](#board) (Kommentare mit Herkunft `system`) oder, mit
`[board] source = "kanzo"`, aus [Kanzo](https://github.com/emanuele-em/kanzo).
Voraussetzung: `[consultations] reviewers` in `config.toml` (siehe
[Konfiguration](konfiguration.md#consultations));
ohne Reviewer-Liste antworten die Endpunkte mit `503`
(`ConsultationsDisabled`). Sicherheit: [Sicherheit](../sicherheit.md#consultations).

`POST /consultations`:

```json
{"task": "api#12", "question": "Ist der Fix richtig?",
 "context": "optional", "reviewers": ["gpt"], "include_previous": false}
```

- `task` (Pflicht): Ticket-Referenz `projekt#nummer` (Kleinbuchstaben).
- `question` (Pflicht, bis 4.000 Zeichen), `context` (optional, bis 8.000).
- `reviewers`: Teilmenge von `[consultations] reviewers`; Standard: alle erlaubten.
- `include_previous`: frühere Conclave-Kommentare des Tickets mitgeben
  (Standard `false`; dann als „frühere Modellausgabe“ gekennzeichnet).
- Kein Feld `channel`: Der Kanal (`human` oder `agent`) ergibt sich aus dem
  Token. Ein `channel` im Body ergibt `400` (`ChannelNotAllowed`); bis v0.4.0
  gab es dort `rest`/`mcp`.
- Antwort `202` mit `id`, `status: "queued"` und `reviewers` (je Reviewer
  Provider und Modell: an diese Provider geht der Ticket-Inhalt).

Fehler: `400` (`ValidationError`, `ReviewerNotAllowed`, `ChannelNotAllowed`),
`403` (`HumanOnlyTicket`: Ticket nur für Menschen, Anfrage mit dem
Agent-Token), `404`
(Ticket unbekannt), `429` (`ConsultationLimit`: `[consultations] max_per_hour` pro
Ticket und Stunde erreicht; gezählt je Zugang, Mensch und Agent getrennt, für die
normalisierte Referenz der Quelle, also `api#012` wie `api#12`; Prüfen und Anlegen
sind ein Schritt), `502` (Kanzo nicht erreichbar oder unbekanntes
Ausgabeformat), `503` (nicht eingerichtet). Bei diesen Fehlern wird nichts
gespeichert.

Ablauf im Hintergrund: Conclave legt die Conversation
`board:<task> · <id>` (bzw. `kanzo:<task> · <id>`) an, fragt alle Reviewer parallel und stellt jede Antwort
als Kommentar zu. Status: `queued` → `running` → `done` | `failed`. Ein Lauf hält
eine Lease, die der Worker verlängert; bleibt sie aus (Server beendet, Worker
abgestürzt), wird `running` nach höchstens zwei Minuten zu `interrupted`, auch
wenn mehrere Server dieselbe Datenbank nutzen. Statuswechsel überschreiben keinen
inzwischen anders gesetzten Status. Wird das Ticket während des Laufs „nur für
Menschen“, stellt Conclave keine Antwort eines Agent-Auftrags zu (`failed`).
Im eigenen Board gelten als frühere Conclave-Kommentare nur solche mit Herkunft
`system`; ein Agent-Kommentar, der eine Kennung nachahmt, bleibt im Prompt. Jeder Kommentar endet mit einer
Schlusszeile wie

`— Zweitmeinung von GPT (openai, gpt-5.6) über Conclave, nicht geprüft · consultation <id>/gpt`

Lange Antworten werden vorher auf `[consultations] comment_max_chars` gekürzt (mit
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

## Board

Arbeitspakete für Menschen und Agenten (Anleitung:
[Mit dem Board arbeiten](../mit-dem-board-arbeiten.md)). Tickets heißen
`projekt#nummer` und liegen unter `/board/v1/projects/<slug>/tasks/<nummer>`.
Spalten aus `[board] statuses` (siehe [Konfiguration](konfiguration.md#board)).

Ticket (`GET` auf das Ticket, Antworten von `POST /board/v1/tasks` und `PATCH`):

```json
{"ref": "api#12", "project": "api", "number": 12, "title": "Login reparieren",
 "initiative": null, "initiative_ref": null,
 "description": "## Abnahme\n...", "tags": ["ui"], "status": "doing",
 "position": 1024.0, "rank": 1024.0, "human": false, "assignee": null, "version": 3,
 "origin": "agent", "created_by": "agent", "kind": "task", "directive": null,
 "review": {"state": "none", "at": null, "red_count": 0, "blocking": null,
            "suggestions": null, "checked": null},
 "created_at": "...", "updated_at": "...", "actor_name": null}
```

`initiative`/`initiative_ref` nennen das Vorhaben (`api/login-3`), `actor_name` den
Anzeigenamen dessen, der angelegt hat (nur mit einer Erweiterung, die Konten kennt;
in Personal `null`; ebenso an Kommentaren und im Verlauf). `GET` auf ein Ticket liefert
zusätzlich `comments`, `last_review`, `status_since` (seit wann es in seiner Spalte
steht), `can_approve` (hat dieser Zugang im Projekt das Freigabe-Recht?) und
`control`.

- **Anlegen** `POST /board/v1/tasks`: `project` und `title` Pflicht, optional
  `description`, `tags`, `human`, `status` (Standard: erste Spalte; Agenten
  nur die erste Spalte, sonst `403`). `origin` und `created_by` setzt der
  Server aus dem Token (`created_by: "import"` für importierte Tickets, leer
  für Tickets von vor dieser Version).
- **Ändern** `PATCH`: nur übergebene Felder. `index` setzt den Platz in der
  (neuen) Spalte, gezählt ohne das Ticket selbst: in der ersten Spalte die
  Priorität (`rank`), sonst die Position. `rank` (Zahl) setzt die Priorität
  direkt; kleiner steht weiter oben. `index` und `rank` nur mit dem
  Mensch-Token, sonst `403 HumanOnly`. Unbekannte Felder ergeben `400`.
  Mit `version` (aus dem zuletzt gelesenen Ticket) wird nur geschrieben, wenn
  das Ticket noch diesen Stand hat; sonst `409 Conflict`.
- **Priorität:** Die erste Spalte und `POST /board/v1/next` folgen `rank`, dann der
  Nummer; neue Tickets bekommen den nächsten Rang. In den anderen Spalten zählt
  die Position (Reihenfolge des Ankommens). Neunummerieren (wenn zwischen zwei
  Karten kein Platz mehr ist) erhöht die `version` der betroffenen Tickets; ein
  vorher gelesener Stand ergibt dann `409` statt eines alten Rangs. Bei der
  Einführung des Rangs bekam jedes vorhandene Ticket seine damalige Position als
  Rang. Positionen zählen je Spalte, daher stehen Tickets, die damals nicht in der
  ersten Spalte waren, beim Zurückschieben dort weit oben, bis der Mensch sie
  umsortiert.
- **`POST /board/v1/next`** (`{"project": "api"}` optional): schiebt das oberste
  Ticket der ersten Spalte ohne Markierung „nur für Menschen“ atomar in die
  zweite und liefert es (`{"task": ...}`, `null` wenn keines frei ist). Mit
  `{"task": "api#12"}` genau dieses Ticket; steht es nicht in der ersten Spalte
  oder wurde inzwischen übernommen, `409 NotClaimable`; „nur für Menschen“
  `403`; unbekannt `404`. Agenten verlassen die erste Spalte nur so: Eine
  Statusänderung per `PATCH` aus der ersten Spalte ergibt `403`.
- **Kommentare** `POST .../comments` mit `body` (Markdown), optional
  `author_name` (Anzeigename). `origin` (`human`/`agent`/`reviewer`/`system`/`null`) und
  `actor_id` setzt der Server aus dem Token; solche Felder im Body werden
  ignoriert.
- **Verlauf** `GET .../history`: `field`, `old`, `new` (vollständig), `origin`,
  `actor_id`, `created_at`. Felder: `created` (Anlegen, `new` = Spalte bzw.
  `import`), `status`, `title`, `description`, `human`, `rank`, `tags` (JSON-Liste),
  `position` (Umsortieren in einer Spalte), `comment` (Bearbeiten: alt → neu,
  Löschen: alt → `null`), `review_state`, `review_red_count`, `control_ack`
  (Quittung eines Hinweises), `initiative` und `assignee`. Gelöschte Kommentare
  verschwinden aus der Liste, ihr Inhalt bleibt im Verlauf.
- **Review** `POST .../review` (nur Reviewer-Zugang, Agent und Mensch `403`):
  `{"state": "running"|"passed"|"rework"|"failed"|"none", "comment": "...",
  "blocking": 0, "suggestions": 3, "checked": "branch @ abc..def"}`. Nur für
  Tickets in der Review-Spalte (sonst `409 NotInReview`); außer bei `running`
  und `none` ist `comment` Pflicht. `none` gibt ein hängendes Review frei und
  geht nur von `running` aus (sonst `409 ReviewNotRunning`). Ergebnis, Kommentar (Herkunft `reviewer`) und Folgen
  werden zusammen gespeichert:
  - `passed` (grün): bleibt in `review`, der Zähler roter Reviews wird 0.
  - `rework` (gelb) und `failed` (rot): zurück in die erste Spalte, dort vor
    allen anderen Tickets (Verlauf mit Herkunft `system`).
  - Das dritte `failed` in Folge macht das Ticket „nur für Menschen“; `rework`
    zählt nicht mit. Nimmt der Mensch die Markierung wieder weg, beginnt die
    Zählung neu (`review_red_count` → 0, mit Verlaufseintrag).
  - Tickets „nur für Menschen“ bewertet der Reviewer nicht (`403`); auch
    `conclave-reviewer` startet für sie kein Review.
  - Bei `POST /board/v1/next` ohne Projekt kommt Nacharbeit (`rework`/`failed`)
    aus allen Projekten zuerst, danach gilt die Board-Reihenfolge.
  - Kommt ein Ticket wieder nach `review`, steht der Status auf `none`.
- **Review neu anfordern** `POST .../review/request` mit leerem Body `{}`
  (Freigabe-Recht, in Personal nur der Mensch; Agent und Reviewer `403`): setzt
  den Status auf `requested`, `at` auf den Zeitpunkt der Anforderung und leert
  `blocking`, `suggestions` und `checked`. Das Ticket bleibt in `review`, der
  Zähler roter Reviews bleibt. `409` mit `NotInReview` außerhalb der
  Review-Spalte, `HumanOnlyTicket` bei „nur für Menschen“ und `ReviewRunning`
  während eines laufenden Reviews. `conclave-reviewer` prüft ein Ticket mit
  `requested` wie ein neu nach `review` geschobenes, je Anforderung einmal.
  Nimmt der Mensch einem Ticket in `review` die Markierung „nur für Menschen“
  weg, setzt das Board `requested` selbst (Herkunft `system`).

  Tickets tragen `review` mit `state` (`none`, `requested`, `running`,
  `passed`, `rework` oder `failed`), `at`, `red_count`, `blocking`,
  `suggestions` und `checked`. `GET` auf ein Ticket und `POST /board/v1/next`
  liefern zusätzlich `last_review`, den jüngsten Kommentar des Reviewers.
- **Steuertickets** (Anweisungen des Menschen an die Agenten): `POST /board/v1/tasks`
  mit `"kind": "control"`, `"control": "pause"|"hint"` und `"scope":
  "project"|"all"`, nur mit dem Mensch-Token (sonst `403`). Ändern und Schließen
  (nach „erledigt“) darf nur der Mensch; `POST /board/v1/next` vergibt sie nie.
  - **Pause:** Solange offen, liefert `POST /board/v1/next` kein Ticket, sondern
    `{"task": null, "paused": true, "pause": {"task", "reason", "by", "scope", …}}`,
    auch mit `task`. Geltung: das Projekt des Steuertickets oder alle; `next`
    ohne Projekt hält jede offene Pause an.
  - **Hinweis:** bleibt offen, bis ein Agent ihn kommentiert; der erste Kommentar
    eines Agenten gilt als Quittung (`directive.ack_by`, Verlauf `control_ack`).
  - Jede Board-Antwort (`/board/v1`, Liste, Suche, Ticket, Anlegen, `PATCH`,
    Kommentar, `next`) trägt `control` mit offenen Pausen (`pauses`) und
    unquittierten Hinweisen (`hints`). Nur Steuertickets mit Herkunft `human`
    zählen; ein normales Ticket mit ähnlichem Text löst nichts aus.
  - Tickets tragen `kind` (`task`/`control`) und bei Steuertickets `directive`
    (`type`, `scope`, `ack_by`, `ack_at`).
- **Projekt-Verlauf** `GET /board/v1/projects/<slug>/history` (nur Mensch):
  `created`, `name` (Umbenennen), `task_deleted` (Referenz, Titel und Spalte
  des gelöschten Tickets) und `initiative` (Vorhaben angelegt oder geändert). Ein gelöschtes Ticket nimmt seinen eigenen Verlauf
  mit; dieser Eintrag bleibt.
- **Spalten umbenennen:** Wird die letzte Spalte in `[board] statuses`
  umbenannt, verschiebt Conclave beim Start die Tickets der alten letzten Spalte
  in die neue (Verlauf mit Herkunft `system`), damit sie erledigt bleiben.

Regeln für das Agent-Token (Fehler `403 HumanOnly`): nicht nach oder aus der
letzten Spalte schieben, erledigte Tickets nur lesen und kommentieren, Tickets
nur in der ersten Spalte anlegen, Tickets „nur für Menschen“ nur lesen, die
Markierung setzen, aber nicht entfernen. Kommentare ändern und löschen nur der
Mensch und nur eigene. Gleichzeitige Änderungen am selben Ticket: `409
Conflict`.

**Import** `POST /board/v1/import` (nur Mensch) nimmt die Ausgabe von
`kanzo export -f json` an, höchstens 50 MB (`413 ImportTooLarge`). Der Export
wird vollständig geprüft, bevor etwas geschrieben wird (`400
ImportFormatError`). Antwort:

```json
{"projects_created": 1, "tasks_imported": 12, "tasks_skipped": 0,
 "comments_imported": 30, "skipped_refs": []}
```

Ticket-Nummern bleiben erhalten; vorhandene Tickets werden übersprungen, ohne
neue Kommentare nachzutragen. Importierte Kommentare haben `origin: null`;
importierte Tickets haben `origin: null`, `created_by: "import"` und als
einzigen Verlaufseintrag `created` mit der Herkunft dessen, der importiert hat.

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
  `{"backup": "conclave-backup-20261030T120000123456Z-3fa2c1.zip"}`. Pfade, `..`,
  Laufwerksangaben und Symlinks aus dem Verzeichnis heraus werden mit `400`
  abgelehnt; das frühere Feld `backup_path` wird nicht mehr unterstützt.
- Standardmäßig bleibt der Workspace erhalten; Dateien aus dem Backup werden
  hinzugefügt bzw. überschrieben. Den Workspace vorher leeren nur mit
  `"replace_workspace": true` **und** `"confirm": "replace-workspace"`.
- Vor jedem Restore wird automatisch ein `conclave-pre-restore-*.zip` angelegt.
  Backup-Namen enthalten Mikrosekunden und einen Zufallsanteil; ein vorhandenes
  Backup wird nie überschrieben.
- Ein Backup enthält nur normale Dateien des Workspace; Symlinks und Junctions
  werden übersprungen.
- Der Restore prüft und entpackt das ganze Archiv zuerst in ein
  Zwischenverzeichnis, tauscht dann den Workspace und spielt die Datenbank
  zuletzt ein. Schlägt ein Schritt fehl, bleiben Datenbank und Workspace
  unverändert. Trigger und Views aus der Backup-Datenbank werden verworfen.
  Ist eine Datei im Workspace geöffnet (unter Windows z. B. im Editor),
  antwortet der Restore mit `409`, `"status": "workspace_busy"`.
- **Herkunft:** Jedes Backup enthält ein `manifest.json` mit Instanz-ID und
  einer Signatur über den Inhalt, abgeleitet aus `secret.key`. Stammt ein Backup
  nicht nachweislich von dieser Instanz (andere Instanz, verändert, ohne
  Manifest wie ältere Backups), antwortet der Restore mit `409`,
  `"status": "origin_unverified"`, dem Grund (`reason`) und den Agents des
  Backups (`agents`: `id`, `api_url`), ohne etwas zu ändern. Nach Prüfung der
  Agents mit `"allow_foreign": true` wiederholen. Die Antwort enthält dann
  `"origin": "foreign"`, sonst `"own"`.
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
  wird nicht gespeichert. Ein Ordner, der Home-, Konfigurations-, Daten-, Log-
  oder Backup-Verzeichnis ist oder enthält, wird mit `400`
  (`WorkspaceNotAllowed`) abgelehnt.

## Workspace-Dateien

- `POST /workspace/<pfad>` erwartet `{"content": "<Text>"}`; anderer Typ →
  `400`. Geschrieben wird über eine temporäre Datei, die alte Datei bleibt bis
  zum Austausch intakt.
- Agenten legen nur neue Dateien an. Vorhandene Dateien überschreibt nur der
  Mensch (`403 HumanOnly`); unter `agents/` dürfen Agenten auch überschreiben.
  `conclave_notify.json` ist für Agenten gesperrt.
- Pfade mit `:`, Windows-Gerätenamen (auch mit Endung), Punkt oder Leerzeichen
  am Ende, Steuerzeichen oder 8.3-Kurznamen → `403`.

## Chat-Regeln und @read

`GET /conversations/<id>/rules` liefert `{"rules": "...", "model_read": false}`.
`POST /conversations/<id>/rules` nimmt `rules` und optional `model_read`
(`true`/`false`): Mit `true` dürfen Modelle in dieser Conversation Dateien per
`@read()` lesen. Ändern (`POST`) nur mit dem Mensch-Token; lesen (`GET`) dürfen
auch Agenten.

## Größengrenzen

Anfragen sind auf 10 MB begrenzt (`413 RequestTooLarge`), der Board-Import auf
50 MB (`413 ImportTooLarge`). Board: Titel höchstens 300 Zeichen,
Beschreibung und Kommentar höchstens 65.536 Zeichen, höchstens 50 Tags zu je 50
Zeichen (sonst `400 ValidationError` bzw. beim Import `ImportFormatError`).

## IDs

Frei wählbare IDs (Participants, neue Agents) bestehen aus 1–64 Zeichen aus
`A-Z`, `a-z`, `0-9`, `.`, `-` und `_`; `.` und `..` allein sind nicht
erlaubt. Sonst antwortet die API mit `400 ValidationError`. Bestehende Agents
mit anderen IDs lassen sich weiter bearbeiten, testen und löschen, aber nicht
mehr als Participant hinzufügen; dafür den Agent mit passender ID neu anlegen.

## Fehlercodes

Fehler kommen als JSON `{"error": "...", "type": "..."}`. Wichtige Codes:

- `400` — ungültige Eingaben, leere Conversation, Provider-Client-Fehler (4xx);
  bei Participants ein `type` außer `model`/`user`
- `401` — Token fehlt oder ist falsch
- `403` — `HumanOnly`: Route nur mit dem Mensch-Token (siehe
  [Mensch- und Agent-Zugang](#mensch--und-agent-zugang)) oder Board-Regel
  (siehe [Board](#board)); `HumanOnlyTicket`: Consultation auf ein Ticket nur
  für Menschen mit dem Agent-Token
- `404` — Conversation, Participant, Agent, Run, Datei, Projekt, Ticket oder
  Kommentar nicht gefunden (auch Invoke in einer unbekannten Conversation)
- `409` — Konflikt (z. B. Agent/Participant/Projekt existiert bereits, kein
  Rederecht, Ticket inzwischen geändert, Rate-Limit durch
  `CONCLAVE_RATE_LIMIT` gesperrt)
- `413` — Anfrage größer als 10 MB (`RequestTooLarge`) bzw. Board-Import größer als 50 MB (`ImportTooLarge`)
- `415` — POST ohne JSON bzw. `X-Conclave-Client`; Binärdatei im Workspace
- `421` — `Host`-Header nicht erlaubt
- `429` — eigenes Rate-Limit überschritten (`RateLimitExceeded`; getrennt nach
  Zugang, Agenten mit eigener Grenze), Grenze für Agenten erreicht
  (`AgentBudgetExceeded`, `ConversationBudgetExceeded`, `TooManyAgentRuns`, siehe
  [Konfiguration](konfiguration.md#grenzen-für-agenten)) oder Provider-Rate-Limit
  nach ausgeschöpften Retries (`ProviderRateLimit`)
- `502` — Provider-Fehler (`ProviderUnavailable` u. a.), kein Adapter
  (`AdapterNotFound`)
- `503` — Board oder Consultations in dieser Instanz nicht verfügbar
- `504` — Provider-Timeout (`ProviderTimeout`)
