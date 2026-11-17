# CLI-Referenz

Conclave Personal nutzt `conclave` als lokales Steuerungs- und Debug-Werkzeug.

## Runtime

```powershell
conclave server [--host 127.0.0.1] [--port 8000] [--debug]
conclave web [--url http://127.0.0.1:8000]
conclave desktop [--host 127.0.0.1] [--port 8000] [--debug]
```

`desktop` startet den lokalen Server und öffnet die Web-UI im Browser.
`web`, `desktop` und `conclave-watch` nutzen das Mensch-Token. `web --url`
übergibt es nur an lokale Adressen (`127.0.0.1`, `localhost`, `::1`), nie an
einen fremden Host.
Wenn der bevorzugte Port belegt ist, wählt `desktop` automatisch einen freien
Port.

## Conversations

```powershell
conclave new
conclave list
conclave show <conversation_id>
conclave delete <conversation_id>
conclave message <conversation_id> <text>
conclave add-participant <conversation_id> <participant_id> --name <name> [--type model|user]
conclave invoke <conversation_id> <participant_id>
conclave stream <conversation_id> <participant_id>
conclave orchestrate <conversation_id> <participant_id>...
conclave orchestrate-parallel <conversation_id> --groups a,b c
conclave auto-loop <conversation_id> <participant_id>... [--stop-signal @done] [--max-rounds 20] [--rotation none|round-robin|round_robin]
conclave watch <conversation_id> [--interval 5] [--since 0]
```

`watch` zeigt die Nachrichten einer Conversation an und pollt danach im
angegebenen Intervall (Sekunden) auf neue Nachrichten (Ctrl+C beendet).
`--since` zeigt nur Nachrichten mit größerer Sequence.

## Thema und Rederecht

```powershell
conclave topic <conversation_id> <topic>
conclave grant <conversation_id> <participant_id>
conclave revoke <conversation_id>
conclave floor-invoke <conversation_id>
```

`grant` erteilt einem Participant das Rederecht, `revoke` entzieht es.
`floor-invoke` ruft den Participant mit Rederecht auf und entzieht das
Rederecht danach.

## Agents

```powershell
conclave agents
conclave agent-new <id> --name <name> --model <model> [Optionen]
conclave agent-edit <id> --name <name> --model <model> [Optionen]
conclave agent-show <id>
conclave agent-delete <id>
conclave agent-set-key <id> <api_key>
conclave agent-test <id>
```

Optionen für `agent-new` und `agent-edit`:

| Option | Default | Bedeutung |
|--------|---------|-----------|
| `--provider` | `anthropic` | Provider-Name |
| `--api-key` | leer | API-Key des Agenten |
| `--role` | leer | Rollenbezeichnung (nur Anzeige, nicht im Prompt) |
| `--topic` | leer | Thema des Agenten (nur Anzeige, nicht im Prompt) |
| `--system-prompt` | leer | System-Prompt |
| `--preset` | leer | Provider-Preset (z. B. `openai-responses`, `ollama`) |
| `--api-url` | leer | Eigene API-URL (überschreibt die Preset-URL) |
| `--response-path` | leer | Pfad zur Antwort im Response-JSON |
| `--message-format` | `standard` | Message-Format (`standard`, `anthropic`, `gemini`, `openai-responses`); `standard` übernimmt das Format des Presets |
| `--max-messages` | leer | Kürzungslimit pro Aufruf: Zahl (`0` = keine Kürzung); leer = globaler Default (`CONCLAVE_MAX_MESSAGES`, nur Preset-Agents). Bei `agent-edit` setzt `default` auf den Default zurück |

`agent-edit` überschreibt alle Felder: Nicht angegebene Optionen werden auf
leer bzw. den Standardwert zurückgesetzt. Ausnahmen sind `--api-key` und
`--max-messages`: ohne Angabe bleiben der gespeicherte Key bzw. das
gespeicherte Limit erhalten. `agent-set-key`
ändert nur den Key und lässt alle anderen Felder unverändert.

## Workspace

```powershell
conclave workspace list
conclave workspace read <path>
conclave workspace write <path> <text>
```

Workspace-Pfade bleiben innerhalb des Workspace: `CONCLAVE_WORKSPACE`, sonst
der Plattformdefault (`~/Conclave/workspace`, unter Windows
`%USERPROFILE%\Conclave\workspace`). Das gilt für alle Kommandos.

## Runs, Usage und Backup

```powershell
conclave runs [--conversation-id <id>] [--limit 100]
conclave usage [--by-conversation]
conclave export <conversation_id>
conclave backup [--dir <backup_dir>]
conclave restore --backup <backup.zip> [--dir <backup_dir>] [--keep-workspace] [--allow-foreign]
```

`backup` erstellt ein ZIP mit lokaler SQLite-DB und Workspace-Dateien. Ohne
`--dir` landet es in `CONCLAVE_BACKUP_DIR`, sonst in
`<Elternordner des Workspace>/backups`.
`restore` stellt die SQLite-DB und Workspace-Dateien aus einem solchen ZIP
wieder her. Vor dem Schreiben wird automatisch ein Pre-Restore-Backup erstellt;
`--dir` legt fest, in welchem Verzeichnis dieses Pre-Restore-Backup landet
(Default wie bei `backup`).
Anders als die API ersetzt die CLI standardmäßig den Workspace-Inhalt; mit
`--keep-workspace` werden Dateien aus dem Backup in den bestehenden Workspace
gemischt.
Der Restore prüft und entpackt erst alles; schlägt ein Schritt fehl, bleiben
Datenbank und Workspace unverändert. Ein Backup ohne belegte Herkunft (andere
Instanz, verändert oder ältere Backups ohne Manifest) spielt `restore` nicht ein,
sondern listet die Agents aus dem Backup mit ihren Ziel-URLs. Nach Prüfung mit
`--allow-foreign` wiederholen. Details:
[API-Referenz, Backup und Restore](api.md#backup-und-restore).

## Migration

```powershell
conclave migrate-personal --from <alte-db> [--to <ziel-db>] [--backup-dir <dir>] [--dry-run]
```

Die Migration übernimmt lokale Conversations, Messages, Participants, Agents
und Usage-/Run-Daten. Consent-, DPA- und Transfer-Policy-Daten werden bewusst
ignoriert. Existiert die Ziel-DB bereits, wird vor dem Schreiben ein Backup
angelegt.

## Tokens

```powershell
conclave token show [--agent | --reviewer] [--reveal]
```

Zeigt, woher ein Token kommt (Variable oder Datei). Ohne `--agent` das
Mensch-Token, mit `--agent` das Agent-Token samt fertigem
`claude mcp add`-Befehl für den MCP-Server; fehlt `agent.token`, wird es
angelegt. Mit `--reviewer` entsprechend das Reviewer-Token und der Befehl für
`conclave-mcp --reviewer`. Den Token-Wert gibt der Befehl nur mit `--reveal` aus.

## Board

```powershell
conclave board initiative list <projekt>
conclave board initiative add <projekt> <kurzname> <titel> [--rank <zahl>]
conclave board initiative rank <projekt> <kurzname> <zahl>
conclave board initiative assign <projekt> <kurzname|-> <ticket>...
```

Vorhaben eines Projekts verwalten (siehe
[Mit dem Board arbeiten](../mit-dem-board-arbeiten.md#vorhaben)). Die CLI
handelt als Mensch und arbeitet direkt auf der konfigurierten Datenbank.
`assign` vergibt die Nummern in der Reihenfolge der Tickets (`projekt#n` oder
nur die Nummer); `-` entfernt die Zuordnung.

## Schlüssel

```powershell
conclave key rotate [--db <pfad>] [--drop-old]
```

Neuer `secret.key`, alle verschlüsselten Daten (SQLite oder PostgreSQL) werden
neu verschlüsselt. Der alte Schlüssel bleibt als `secret.key.old-<Zeit>` für
ältere Backups erhalten; mit `--drop-old` werden alle abgelösten Schlüssel
gelöscht (nach einer Kompromittierung, ältere Backups gelten dann als fremd).
`--db` gilt nur für SQLite. Danach den Server neu starten. Siehe
[Sicherheit](../sicherheit.md#schlüsselwechsel).

## JSON-Ausgabe

`--json` ist eine globale Option und steht **vor** dem Subkommando:

```powershell
conclave --json list
conclave --json show <conversation_id>
```

`auto-loop` gibt mit `--json` jedes Event als eigene JSON-Zeile aus.
`stream`, `watch`, `server`, `desktop` und `web` ignorieren `--json`.

## Weitere Programme

Neben `conclave` installiert das Paket diese Konsolenprogramme:

| Programm | Zweck |
|----------|-------|
| `conclave-api` | Startet den API-Server direkt (ohne die Launch-Logik von `conclave server`) |
| `conclave-mcp` | MCP-Server, der die Conclave-API über `CONCLAVE_API_URL` (Default `http://localhost:8000`) anspricht. Nutzt nur das Agent-Token (`CONCLAVE_AGENT_KEY` bzw. `agent.token`), nie `api.token` oder `CONCLAVE_API_KEY`; mit dem Mensch-Token lehnt jedes Tool ab (Ausnahme zur Fehlersuche: `CONCLAVE_MCP_ALLOW_HUMAN=1`) |
| `conclave-watch` | Beobachtet eine Conversation über die HTTP-API |
| `conclave-reviewer` | Automatischer Reviewer für das Board (Extra `reviewer`); startet sonst mit `conclave desktop` |

```powershell
conclave-watch <conversation_id> [--api http://localhost:8000] [--interval 5] [--since 0] [--full] [--key <token>]
```

`--api` muss eine `http(s)`-URL sein. `--full` zeigt Nachrichten vollständig
statt nur der ersten Zeile. Ohne `--key` wird das Token aus
`CONCLAVE_API_KEY` oder der lokalen Token-Datei `api.token` gelesen.
