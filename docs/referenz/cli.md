# CLI-Referenz

Conclave Personal nutzt `conclave` als lokales Steuerungs- und Debug-Werkzeug.

## Runtime

```powershell
conclave server [--host 127.0.0.1] [--port 8000] [--debug]
conclave web [--url http://127.0.0.1:8000]
conclave desktop [--host 127.0.0.1] [--port 8000] [--debug]
```

`desktop` startet den lokalen Server und öffnet die Web-UI im Browser.
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
conclave auto-loop <conversation_id> <participant_id>... [--stop-signal @done] [--max-rounds 20] [--rotation none|round-robin]
```

## Agents

```powershell
conclave agents
conclave agent-new <id> --name <name> --provider <provider> --model <model> [--preset <preset>]
conclave agent-edit <id> --name <name> --provider <provider> --model <model>
conclave agent-show <id>
conclave agent-delete <id>
conclave agent-set-key <id> <api_key>
conclave agent-test <id>
```

## Workspace

```powershell
conclave workspace list
conclave workspace read <path>
conclave workspace write <path> <text>
```

Workspace-Pfade bleiben innerhalb `CONCLAVE_WORKSPACE`.

## Runs, Usage und Backup

```powershell
conclave runs [--conversation-id <id>] [--limit 100]
conclave usage [--by-conversation]
conclave export <conversation_id>
conclave backup [--dir <backup_dir>]
conclave restore --backup <backup.zip> [--dir <backup_dir>] [--keep-workspace]
```

`backup` erstellt ein ZIP mit lokaler SQLite-DB und Workspace-Dateien.
`restore` stellt die SQLite-DB und Workspace-Dateien aus einem solchen ZIP
wieder her. Vor dem Schreiben wird automatisch ein Pre-Restore-Backup erstellt.
Standardmäßig ersetzt Restore den Workspace-Inhalt; mit `--keep-workspace`
werden Dateien aus dem Backup in den bestehenden Workspace gemischt.

## Migration

```powershell
conclave migrate-personal --from <alte-db> [--to <ziel-db>] [--backup-dir <dir>] [--dry-run]
```

Die Migration übernimmt lokale Conversations, Messages, Participants, Agents
und Usage-/Run-Daten. Consent-, DPA- und Transfer-Policy-Daten werden bewusst
ignoriert. Existiert die Ziel-DB bereits, wird vor dem Schreiben ein Backup
angelegt.

Alle Kommandos unterstützen `--json`, sofern sie strukturierte Ergebnisse
zurückgeben.
