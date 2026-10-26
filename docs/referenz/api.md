# API-Referenz

**47 dokumentierte Endpoints** — öffentliche Personal-API.

Alle Endpoints außer `GET /`, `/static/*`, `GET /health`, `GET /api-docs` und
`GET /openapi.json` verlangen ein Token (`Authorization: Bearer <token>` oder
`X-API-Key`). POST-Anfragen brauchen `Content-Type: application/json` (auch ohne
Inhalt: `{}`) oder den Header `X-Conclave-Client`. Anfragen mit nicht erlaubtem
`Host`-Header werden mit `421` abgelehnt. Details: [Sicherheit](../sicherheit.md).

| Methode | Pfad | Beschreibung |
|---------|------|-------------|
| `GET` | `/` | Serve Ui |
| `POST` | `/guard/notify` | Leitet eine Benachrichtigung an den Guard-Service weiter. |
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
| `GET` | `/conversations/<conversation_id>/tool-events` | List Tool Events |
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
| `PUT` | `/settings` | Aktualisiert einfache Runtime-Settings für die laufende Session. |
| `POST` | `/backup` | Erstellt ein lokales ZIP-Backup von SQLite-DB und Workspace. |
| `POST` | `/restore` | Stellt SQLite-DB und Workspace aus einem lokalen ZIP-Backup wieder her. |
| `GET` | `/workspace` | Listet alle Dateien im Workspace. |
| `GET` | `/workspace/<path:filepath>` | Liest eine Datei aus dem Workspace. |
| `POST` | `/workspace/<path:filepath>` | Schreibt eine Datei in den Workspace. |
| `DELETE` | `/workspace/<path:filepath>` | Löscht eine Datei aus dem Workspace. |

*Generiert: 2026-08-11*
