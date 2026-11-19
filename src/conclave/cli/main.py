# src/conclave/cli/main.py

import argparse
import json
import os
import sys

from conclave.cli.bootstrap import build_agent_service, build_registry, build_service, validate_production_config
from conclave.cli.config import ConclaveConfig
from conclave.cli.handler import CLIHandler, CLIResult
from conclave.domain.participant import ParticipantType
from conclave.infrastructure.log import configure_logging, get_logger
from conclave.runtime.browser import open_browser
from conclave.runtime.desktop import prepare_launch_config
from conclave.runtime.env import env_secret


def _console_symbol(symbol: str, fallback: str, stream=None) -> str:
    stream = stream or sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        symbol.encode(encoding)
    except UnicodeEncodeError:
        return fallback
    return symbol


def _ok(stream=None) -> str:
    return _console_symbol("✓", "OK", stream)


def _err(stream=None) -> str:
    return _console_symbol("✗", "ERROR", stream)


def print_result(result: CLIResult, output_json: bool = False) -> None:
    if output_json:
        print(json.dumps({"success": result.success, "message": result.message, **result.data}, indent=2, default=str))
        return

    icon = _ok() if result.success else _err()
    print(f"{icon} {result.message}")

    if result.success and result.data:
        for key, value in result.data.items():
            if key in ("messages", "participants") and isinstance(value, list):
                if value:
                    print(f"\n  {key}:")
                    for item in value:
                        if key == "messages":
                            author = item.get("author_id") or item.get("author_type")
                            print(f"    [{item['sequence']}] {author}: {item['content']}")
                        else:
                            print(f"    • {item['name']} ({item['id']}, {item['type']})")
            elif key == "agents" and isinstance(value, list):
                if not value:
                    print("  Keine Agenten konfiguriert.")
                else:
                    for a in value:
                        role  = f" [{a['role']}]"    if a.get("role")  else ""
                        topic = f" – {a['topic']}"   if a.get("topic") else ""
                        print(f"  {a['id']:20} {a['name']:20} {a['provider']:10} {a['model']}{role}{topic}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="conclave",
        description="Host-gesteuertes Multi-Model-Konversationssystem",
    )
    parser.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    # ── Runtime ─────────────────────────────────────────────────────────
    server_p = sub.add_parser("server", help="Lokalen API-Server starten")
    server_p.add_argument("--host", default=None)
    server_p.add_argument("--port", type=int, default=None)
    server_p.add_argument("--debug", action="store_true")

    web_p = sub.add_parser("web", help="Web-UI im Browser oeffnen")
    web_p.add_argument("--url", default=None)

    desktop_p = sub.add_parser("desktop", help="Lokale App starten und im Browser oeffnen")
    desktop_p.add_argument("--host", default=None)
    desktop_p.add_argument("--port", type=int, default=None)
    desktop_p.add_argument("--debug", action="store_true")

    # ── Conversations ────────────────────────────────────────────────────
    sub.add_parser("new",  help="Neue Conversation erstellen")
    sub.add_parser("list", help="Alle Conversations auflisten")

    del_p = sub.add_parser("delete", help="Conversation löschen")
    del_p.add_argument("conversation_id")

    show_p = sub.add_parser("show", help="Conversation anzeigen")
    show_p.add_argument("conversation_id")

    add_p = sub.add_parser("add-participant", help="Participant registrieren")
    add_p.add_argument("conversation_id")
    add_p.add_argument("participant_id")
    add_p.add_argument("--name", required=True)
    add_p.add_argument("--type", dest="participant_type", choices=["model", "user"], default="model")

    msg_p = sub.add_parser("message", help="User-Message hinzufügen")
    msg_p.add_argument("conversation_id")
    msg_p.add_argument("content")

    inv_p = sub.add_parser("invoke", help="Participant aufrufen")
    inv_p.add_argument("conversation_id")
    inv_p.add_argument("participant_id")

    stream_p = sub.add_parser("stream", help="Participant mit Token-Streaming aufrufen")
    stream_p.add_argument("conversation_id")
    stream_p.add_argument("participant_id")

    orch_p = sub.add_parser("orchestrate", help="Mehrere Participants der Reihe nach aufrufen")
    orch_p.add_argument("conversation_id")
    orch_p.add_argument("participants", nargs="+", metavar="participant_id")

    porch_p = sub.add_parser("orchestrate-parallel", help="Participants parallel in Gruppen aufrufen")
    porch_p.add_argument("conversation_id")
    porch_p.add_argument("--groups", nargs="+", required=True, metavar="GROUP",
                         help="Gruppen von participant_ids (kommagetrennt), z.B. --groups a,b c")

    loop_p = sub.add_parser("auto-loop", help="Agenten bis Stop-Signal diskutieren lassen")
    loop_p.add_argument("conversation_id")
    loop_p.add_argument("participants", nargs="+", metavar="participant_id")
    loop_p.add_argument("--stop-signal", default="@done")
    loop_p.add_argument("--max-rounds", type=int, default=20)
    loop_p.add_argument(
        "--rotation",
        choices=["none", "round-robin", "round_robin"],
        default="none",
        help="Antwortreihenfolge pro Runde rotieren lassen",
    )

    # ── Thema & Rederecht ────────────────────────────────────────────────
    topic_p = sub.add_parser("topic", help="Thema einer Conversation setzen")
    topic_p.add_argument("conversation_id")
    topic_p.add_argument("topic")

    grant_p = sub.add_parser("grant", help="Rederecht an Participant erteilen")
    grant_p.add_argument("conversation_id")
    grant_p.add_argument("participant_id")

    revoke_p = sub.add_parser("revoke", help="Rederecht entziehen")
    revoke_p.add_argument("conversation_id")

    floor_p = sub.add_parser("floor-invoke", help="Participant mit Rederecht aufrufen")
    floor_p.add_argument("conversation_id")

    # ── Agenten ──────────────────────────────────────────────────────────
    sub.add_parser("agents", help="Alle Agenten auflisten")

    agent_new = sub.add_parser("agent-new", help="Agenten erstellen")
    agent_new.add_argument("id")
    agent_new.add_argument("--name",          required=True)
    agent_new.add_argument("--provider",      default="anthropic")
    agent_new.add_argument("--model",         required=True)
    agent_new.add_argument("--api-key",       default="", dest="api_key")
    agent_new.add_argument("--role",          default="")
    agent_new.add_argument("--topic",         default="")
    agent_new.add_argument("--system-prompt", default="", dest="system_prompt")
    agent_new.add_argument("--preset",        default="")
    agent_new.add_argument("--api-url",       default="", dest="api_url")
    agent_new.add_argument("--response-path", default="", dest="response_path")
    agent_new.add_argument("--message-format", default="standard", dest="message_format")
    agent_new.add_argument("--max-messages", default=None, type=int, dest="max_messages",
                           help="Kuerzungslimit (0 = keine Kuerzung, leer = globaler Default)")

    agent_edit = sub.add_parser("agent-edit", help="Agenten bearbeiten")
    agent_edit.add_argument("id")
    agent_edit.add_argument("--name",          required=True)
    agent_edit.add_argument("--provider",      default="anthropic")
    agent_edit.add_argument("--model",         required=True)
    agent_edit.add_argument("--api-key",       default=None, dest="api_key",
                            help="API-Key aktualisieren (leer lassen = bestehenden behalten)")
    agent_edit.add_argument("--role",          default="")
    agent_edit.add_argument("--topic",         default="")
    agent_edit.add_argument("--system-prompt", default="", dest="system_prompt")
    agent_edit.add_argument("--preset",        default="")
    agent_edit.add_argument("--api-url",       default="", dest="api_url")
    agent_edit.add_argument("--response-path", default="", dest="response_path")
    agent_edit.add_argument("--message-format", default="standard", dest="message_format")
    agent_edit.add_argument("--max-messages", default=None, dest="max_messages",
                            help="Kuerzungslimit: Zahl (0 = keine Kuerzung) oder 'default'; "
                                 "weglassen = bestehenden Wert behalten")

    agent_del = sub.add_parser("agent-delete", help="Agenten löschen")
    agent_del.add_argument("id")

    agent_show = sub.add_parser("agent-show", help="Agenten anzeigen")
    agent_show.add_argument("id")

    agent_key = sub.add_parser("agent-set-key", help="API-Key eines Agenten setzen")
    agent_key.add_argument("id")
    agent_key.add_argument("api_key", metavar="API_KEY")

    agent_test = sub.add_parser("agent-test", help="Agent-Verbindung testen")
    agent_test.add_argument("id")

    exp = sub.add_parser("export", help="Conversation exportieren")
    exp.add_argument("conversation_id")

    runs_p = sub.add_parser("runs", help="Runs anzeigen")
    runs_p.add_argument("--conversation-id", default=None)
    runs_p.add_argument("--limit", type=int, default=100)

    usage_p = sub.add_parser("usage", help="Token-Verbrauch anzeigen")
    usage_p.add_argument("--by-conversation", action="store_true")

    workspace_p = sub.add_parser("workspace", help="Workspace verwalten")
    workspace_sub = workspace_p.add_subparsers(dest="workspace_command", required=True)
    workspace_sub.add_parser("list", help="Dateien im Workspace anzeigen")
    workspace_read = workspace_sub.add_parser("read", help="Datei aus Workspace lesen")
    workspace_read.add_argument("path")
    workspace_write = workspace_sub.add_parser("write", help="Text in Workspace-Datei schreiben")
    workspace_write.add_argument("path")
    workspace_write.add_argument("content")

    backup_p = sub.add_parser("backup", help="Lokales ZIP-Backup erstellen")
    backup_p.add_argument("--dir", default=None, dest="backup_dir")

    restore_p = sub.add_parser("restore", help="Lokales ZIP-Backup wiederherstellen")
    restore_p.add_argument("--backup", required=True, dest="backup_path")
    restore_p.add_argument("--dir", default=None, dest="backup_dir")
    restore_p.add_argument("--keep-workspace", action="store_true",
                           help="Workspace-Dateien zusammenfuehren statt vorhandenen Workspace zu ersetzen")
    restore_p.add_argument("--allow-foreign", action="store_true",
                           help="Backup ohne belegte Herkunft (andere Instanz) nach Pruefung trotzdem einspielen")

    migrate_p = sub.add_parser("migrate-personal", help="Alte lokale SQLite-Daten nach Conclave Personal migrieren")
    migrate_p.add_argument("--from", required=True, dest="source_path", help="Pfad zur alten SQLite-DB")
    migrate_p.add_argument("--to", default=None, dest="target_path", help="Ziel-DB, Default ist die aktive Conclave-DB")
    migrate_p.add_argument("--backup-dir", default=None, dest="backup_dir", help="Ordner fuer das Ziel-DB-Backup")
    migrate_p.add_argument("--dry-run", action="store_true", help="Nur pruefen und Bericht ausgeben")

    token_p = sub.add_parser("token", help="API-Tokens anzeigen (Pfad, MCP-Einrichtung)")
    token_sub = token_p.add_subparsers(dest="token_command", required=True)
    token_show = token_sub.add_parser("show", help="Pfad des Tokens und Einrichtungsbefehl anzeigen")
    token_show.add_argument("--agent", action="store_true",
                            help="Agent-Token fuer den MCP-Server statt des Mensch-Tokens")
    token_show.add_argument("--reviewer", action="store_true",
                            help="Reviewer-Token fuer den automatischen Reviewer (conclave-mcp --reviewer)")
    token_show.add_argument("--reveal", action="store_true",
                            help="Den Token-Wert ausgeben (nur auf ausdrueckliche Anfrage)")

    board_p = sub.add_parser("board", help="Board verwalten (als Mensch, direkt auf der Datenbank) und warten")
    board_sub = board_p.add_subparsers(dest="board_command", required=True)
    from conclave.cli import board_wait
    board_wait.add_parser(board_sub)
    ini_p = board_sub.add_parser("initiative", help="Vorhaben eines Projekts (P2)")
    ini_sub = ini_p.add_subparsers(dest="initiative_command", required=True)
    ini_list = ini_sub.add_parser("list", help="Vorhaben nach Rang anzeigen")
    ini_list.add_argument("project")
    ini_add = ini_sub.add_parser("add", help="Vorhaben anlegen")
    ini_add.add_argument("project")
    ini_add.add_argument("slug", help="Kurzname, z. B. sich")
    ini_add.add_argument("title")
    ini_add.add_argument("--rank", type=float, default=None, help="Rang (kleiner = frueher); Default: hinten")
    ini_rank = ini_sub.add_parser("rank", help="Rang eines Vorhabens setzen")
    ini_rank.add_argument("project")
    ini_rank.add_argument("slug")
    ini_rank.add_argument("rank", type=float)
    ini_assign = ini_sub.add_parser("assign", help="Tickets in dieser Reihenfolge zuordnen (naechste Nummern)")
    ini_assign.add_argument("project")
    ini_assign.add_argument("slug", help="Vorhaben; '-' = Zuordnung entfernen")
    ini_assign.add_argument("tasks", nargs="+", help="Referenzen wie conclave#31 oder nur Nummern")

    key_p = sub.add_parser("key", help="Schluessel fuer die verschluesselten Daten (secret.key)")
    key_sub = key_p.add_subparsers(dest="key_command", required=True)
    key_rotate = key_sub.add_parser("rotate", help="Neuen Schluessel erzeugen und alle Daten neu verschluesseln")
    key_rotate.add_argument("--db", default=None, help="SQLite-DB, Default ist die aktive Conclave-DB")
    key_rotate.add_argument("--drop-old", action="store_true",
                            help="Abgeloeste Schluessel loeschen (nach Kompromittierung; aeltere Backups gelten "
                                 "dann als fremd)")

    watch = sub.add_parser("watch", help="Conversation live beobachten (pollt auf neue Nachrichten)")
    watch.add_argument("conversation_id")
    watch.add_argument("--interval", type=int, default=5, help="Poll-Intervall in Sekunden (Default: 5)")
    watch.add_argument("--since", type=int, default=0, help="Ab welcher Sequence starten (Default: 0 = alle)")

    return parser


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "web":
        return _run_web(args)
    if args.command == "server":
        return _run_server(args, should_open_browser=False)
    if args.command == "desktop":
        return _run_server(args, should_open_browser=True)
    if args.command == "migrate-personal":
        return _run_migrate_personal(args)
    if args.command == "token":
        return _run_token_show(args)
    if args.command == "key":
        return _run_key_rotate(args)
    if args.command == "board":
        return _run_board(args)

    config = ConclaveConfig.from_sources()
    errors = validate_production_config(config)
    if errors:
        for e in errors:
            print(f"FEHLER: {e}", file=sys.stderr)
        return 1

    service       = build_service(config=config)
    agent_service = build_agent_service(config=config)
    build_registry(service, agent_service=agent_service, config=config)
    handler = CLIHandler(service, agent_service=agent_service)

    output_json = getattr(args, "json", False)

    # ── Conversations ────────────────────────────────────────────────────
    if args.command == "new":
        result = handler.new_conversation()

    elif args.command == "list":
        result = handler.list_conversations()
        if result.success and not output_json:
            for c in result.data.get("conversations", []):
                print(f"  {c['id']}  [{c['status']}]  {c['created_at']}")
            if not result.data.get("conversations"):
                print("  Keine Conversations vorhanden.")
            return 0

    elif args.command == "show":
        result = handler.show_conversation(args.conversation_id)

    elif args.command == "delete":
        result = handler.delete_conversation(args.conversation_id)

    elif args.command == "add-participant":
        ptype = ParticipantType.MODEL if args.participant_type == "model" else ParticipantType.USER
        result = handler.add_participant(
            conversation_id=args.conversation_id,
            participant_id=args.participant_id,
            name=args.name,
            participant_type=ptype,
        )

    elif args.command == "message":
        result = handler.add_message(args.conversation_id, args.content)

    elif args.command == "invoke":
        result = handler.invoke_participant(args.conversation_id, args.participant_id)

    elif args.command == "stream":
        try:
            for token in handler.stream_participant(args.conversation_id, args.participant_id):
                print(token, end="", flush=True)
            print()
            return 0
        except Exception as e:
            print(f"\n{_err(sys.stderr)} {e}", file=sys.stderr)
            return 1

    elif args.command == "orchestrate":
        result = handler.orchestrate(args.conversation_id, args.participants)

    elif args.command == "orchestrate-parallel":
        groups = [g.split(",") for g in args.groups]
        result = handler.orchestrate_parallel(args.conversation_id, groups)

    elif args.command == "auto-loop":
        try:
            for event in handler.auto_loop(
                args.conversation_id,
                args.participants,
                stop_signal=args.stop_signal,
                max_rounds=args.max_rounds,
                rotation=args.rotation,
            ):
                if output_json:
                    print(json.dumps(event, default=str))
                else:
                    kind = event.get("event", "?")
                    detail = event.get("participant") or event.get("reason") or ""
                    print(f"{kind}: {detail}".rstrip())
            return 0
        except ValueError as exc:
            if output_json:
                print(json.dumps({"success": False, "error": str(exc)}))
            else:
                print(f"{_err(sys.stderr)} {exc}", file=sys.stderr)
            return 1

    elif args.command == "topic":
        result = handler.set_topic(args.conversation_id, args.topic)

    elif args.command == "grant":
        result = handler.grant_floor(args.conversation_id, args.participant_id)

    elif args.command == "revoke":
        result = handler.revoke_floor(args.conversation_id)

    elif args.command == "floor-invoke":
        result = handler.invoke_with_floor(args.conversation_id)

    # ── Agenten ──────────────────────────────────────────────────────────
    elif args.command == "agents":
        result = handler.list_agents()
        if result.success and not output_json:
            print_result(result, output_json=False)
            return 0

    elif args.command == "agent-new":
        from conclave.domain.agent import Agent
        try:
            agent = Agent(id=args.id, name=args.name, provider=args.provider,
                          model=args.model, api_key=args.api_key,
                          role=args.role, topic=args.topic,
                          system_prompt=args.system_prompt,
                          preset=args.preset, api_url=args.api_url,
                          response_path=args.response_path,
                          message_format=args.message_format,
                          max_messages=args.max_messages)
        except ValueError as e:
            print(f"{_err(sys.stderr)} {e}", file=sys.stderr)
            return 1
        result = handler.create_agent(agent)

    elif args.command == "agent-edit":
        from conclave.domain.agent import Agent
        existing = handler.get_agent(args.id)
        from datetime import datetime
        created_at = datetime.fromisoformat(existing.data["created_at"]) if existing.success else None
        # api_key: explizit uebergeben; leer = gespeicherten Key behalten (handler.update_agent)
        api_key = args.api_key or ""
        # max_messages: weglassen = behalten, "default" = globaler Default, Zahl = Limit
        if args.max_messages is None:
            max_messages = existing.data.get("max_messages") if existing.success else None
        elif str(args.max_messages).strip().lower() in ("default", ""):
            max_messages = None
        else:
            try:
                max_messages = int(args.max_messages)
            except ValueError:
                print(f"{_err(sys.stderr)} --max-messages: Zahl oder 'default' erwartet", file=sys.stderr)
                return 1
        try:
            agent = Agent(id=args.id, name=args.name, provider=args.provider,
                          model=args.model, api_key=api_key,
                          role=args.role, topic=args.topic,
                          system_prompt=args.system_prompt,
                          preset=args.preset, api_url=args.api_url,
                          response_path=args.response_path,
                          message_format=args.message_format,
                          max_messages=max_messages,
                          created_at=created_at)
        except ValueError as e:
            print(f"{_err(sys.stderr)} {e}", file=sys.stderr)
            return 1
        result = handler.update_agent(agent)

    elif args.command == "agent-set-key":
        result = handler.set_agent_key(args.id, args.api_key)

    elif args.command == "agent-test":
        data = handler.test_agent(args.id)
        result = CLIResult(success=bool(data.get("success")), message=data.get("message", ""), data=data)

    elif args.command == "agent-delete":
        result = handler.delete_agent(args.id)

    elif args.command == "agent-show":
        result = handler.get_agent(args.id)
        if result.success and not output_json:
            d = result.data
            print(f"  ID:            {d['id']}")
            print(f"  Name:          {d['name']}")
            print(f"  Provider:      {d['provider']}")
            print(f"  Modell:        {d['model']}")
            api_key_status = f"{_ok()} gesetzt" if d.get("api_key_set") else f"{_err()} nicht gesetzt"
            print(f"  API-Key:       {api_key_status}")
            if d.get("role"):  print(f"  Rolle:         {d['role']}")
            if d.get("topic"): print(f"  Thema:         {d['topic']}")
            if d.get("system_prompt"):
                print(f"  System-Prompt: {d['system_prompt'][:80]}{'…' if len(d['system_prompt'])>80 else ''}")
            return 0

    elif args.command == "export":
        result = handler.export_conversation(args.conversation_id)

    elif args.command == "runs":
        result = handler.list_runs(conversation_id=args.conversation_id, limit=args.limit)
        if result.success and not output_json:
            runs = result.data.get("runs", [])
            if not runs:
                print("  Keine Runs vorhanden.")
                return 0
            for r in runs:
                participants = ",".join(r.get("participants", []))
                usage = r.get("usage") or {}
                tokens = usage.get("total_tokens")
                token_text = f"  {tokens} Tokens" if tokens is not None else ""
                print(f"  {r['started_at']}  {r['status']:9}  {r['kind']:10}  {participants}{token_text}")
            return 0

    elif args.command == "usage":
        result = handler.conversation_usage() if args.by_conversation else handler.token_usage()

    elif args.command == "workspace":
        if args.workspace_command == "list":
            result = handler.workspace_list()
            if result.success and not output_json:
                files = result.data.get("files", [])
                if not files:
                    print("  Keine Dateien im Workspace.")
                    return 0
                for f in files:
                    print(f"  {f['path']}  {f['size']} bytes")
                return 0
        elif args.workspace_command == "read":
            result = handler.workspace_read(args.path)
            if result.success and not output_json:
                print(result.data.get("content", ""))
                return 0
        elif args.workspace_command == "write":
            result = handler.workspace_write(args.path, args.content)
        else:
            parser.print_help()
            return 1

    elif args.command == "backup":
        backup_dir = None
        if args.backup_dir:
            from pathlib import Path
            backup_dir = Path(args.backup_dir)
        result = handler.create_backup(db_path=config.db_path, backup_dir=backup_dir)

    elif args.command == "restore":
        from pathlib import Path
        backup_dir = Path(args.backup_dir) if args.backup_dir else None
        result = handler.restore_backup(
            backup_path=Path(args.backup_path),
            db_path=config.db_path,
            backup_dir=backup_dir,
            replace_workspace=not args.keep_workspace,
            allow_foreign=args.allow_foreign,
        )

    elif args.command == "watch":
        return _run_watch(handler, args)

    else:
        parser.print_help()
        return 1

    print_result(result, output_json=output_json)
    return 0 if result.success else 1


def _run_watch(handler: CLIHandler, args) -> int:
    """Beobachtet eine Conversation und gibt neue Nachrichten auf stdout aus."""
    import time
    conv_id = args.conversation_id
    interval = args.interval
    last_seq = args.since

    # Initiale Anzeige
    result = handler.show_conversation(conv_id)
    if not result.success:
        print(f"Fehler: {result.message}", file=sys.stderr)
        return 1

    messages = result.data.get("messages", [])
    topic = result.data.get("topic", "")
    print(f"=== Conclave Watch: {conv_id[:8]}{'… ' + topic if topic else ''} ===")
    print(f"--- {len(messages)} Nachrichten, Intervall {interval}s, Ctrl+C zum Beenden ---")
    print()

    # Bestehende Nachrichten ab since anzeigen
    for m in messages:
        if m["sequence"] > last_seq:
            _print_message(m)
            last_seq = m["sequence"]

    # Poll-Loop
    try:
        while True:
            time.sleep(interval)
            result = handler.show_conversation(conv_id)
            if not result.success:
                continue
            for m in result.data.get("messages", []):
                if m["sequence"] > last_seq:
                    _print_message(m)
                    last_seq = m["sequence"]
    except KeyboardInterrupt:
        print("\n--- Watch beendet ---")
        return 0


def _print_message(m: dict) -> None:
    """Gibt eine einzelne Nachricht formatiert auf stdout aus."""
    author = m.get("author_id") or "User"
    seq = m.get("sequence", "?")
    content = m.get("content", "")
    # Erste Zeile + Truncation fuer lange Nachrichten
    lines = content.strip().split("\n")
    first_line = lines[0][:120] + ("…" if len(lines[0]) > 120 else "")
    more = f" (+{len(lines)-1} Zeilen)" if len(lines) > 1 else ""
    print(f"[#{seq} {author}] {first_line}{more}")


def _server_url(host: str, port: int) -> str:
    from conclave.runtime.browser import server_url
    return server_url(host, port)


def _ui_url(config, base: str) -> str:
    """Startseite im Browser: im Board-Modus gleich die Board-Seite (U2)."""
    from conclave.cli.config import BOARD_PAGE_PATH
    ui = getattr(config, "ui", None)
    return base + BOARD_PAGE_PATH if ui is not None and ui.board_only else base


def _run_web(args) -> int:
    from conclave.runtime.api_token import read_token
    from conclave.runtime.browser import is_local_url, url_with_token

    config = ConclaveConfig.from_sources()
    url = args.url or _ui_url(config, _server_url(config.host, config.port))
    # Das Mensch-Token nur an eine lokale Adresse haengen, nie an einen fremden Host (R5)
    own = not args.url or is_local_url(url)
    open_browser(url_with_token(url, read_token()) if own else url)
    print(f"Conclave Web: {url}")
    return 0


def _run_server(args, should_open_browser: bool = False) -> int:
    config = ConclaveConfig.from_sources()
    launch = prepare_launch_config(
        config,
        host=args.host,
        port=args.port,
        debug=getattr(args, "debug", False),
        open_browser=should_open_browser,
    )
    from conclave.infrastructure.log import LOG_FILE_NAME
    log_file = launch.paths.log_dir / LOG_FILE_NAME
    configure_logging(launch.config.log_level, log_file)
    get_logger("cli.server").info(
        "Server starting",
        extra={"method": "server", "path": str(log_file)},
    )

    from conclave.api.server import _build_app
    from conclave.runtime.api_token import token_path
    from conclave.runtime.browser import url_with_token

    app, config = _build_app(launch.config)
    if should_open_browser:
        import threading
        browser_url = url_with_token(_ui_url(config, launch.url), config.api_key)
        threading.Timer(1.0, lambda: open_browser(browser_url)).start()
        print(f"Conclave Desktop: {launch.url}")
    print(f"Conclave Logs: {log_file}")
    if not env_secret("CONCLAVE_API_KEY"):
        print(f"Conclave API-Token: {token_path()}")
    from conclave.runtime.serve import serve
    reviewer = None
    if should_open_browser:                    # nur conclave desktop startet den Reviewer (W4, E-W3)
        from conclave.runtime.reviewer_launch import start_reviewer
        log = get_logger("cli.reviewer")
        reviewer = start_reviewer(lambda msg: (log.info(msg), print(f"Conclave Reviewer: {msg}")))
    try:
        serve(app, config.host, config.port, debug=config.debug)
    finally:
        if reviewer is not None:
            from conclave.runtime.reviewer_launch import stop_reviewer
            stop_reviewer(reviewer)
    return 0


def _show_reviewer_token(args, url: str) -> int:
    """Reviewer-Token (P3): nur fuer den automatischen Reviewer, nie fuer cc oder andere Agenten."""
    from conclave.runtime import api_token

    if env_secret("CONCLAVE_REVIEWER_KEY"):
        token, source = env_secret("CONCLAVE_REVIEWER_KEY"), "CONCLAVE_REVIEWER_KEY"
    else:
        path = api_token.reviewer_token_path()
        existed = path.exists()
        token, source = api_token.load_or_create_reviewer_token(path), str(path)
        if not existed:
            source += " (neu angelegt)"
    print(f"Reviewer-Token: {source}")
    print("Nur fuer den automatischen Reviewer. Agenten, die Code schreiben, duerfen es nicht lesen "
          "(im Agent-Host sperren wie api.token).")
    print()
    print("MCP-Server fuer den Reviewer (liest reviewer.token selbst):")
    print(f"  claude mcp add ConclaveReviewer -e CONCLAVE_API_URL={url} -- conclave-mcp --reviewer")
    if args.reveal:
        print()
        print(token)
    return 0


def _run_board(args) -> int:
    """Vorhaben verwalten (P2). Die CLI handelt als Mensch, wie alle lokalen Befehle.
    ``wait`` (P8) geht dagegen ueber REST mit dem Agent-Token."""
    if args.board_command == "wait":
        from conclave.cli import board_wait
        return board_wait.run(args)
    from conclave.application.board import BoardError
    from conclave.domain.principal import HUMAN_PRINCIPAL

    config = ConclaveConfig.from_sources()
    board, close = _open_board(config)
    try:
        if args.initiative_command == "add":
            ini = board.create_initiative(HUMAN_PRINCIPAL, args.project, args.slug, args.title, rank=args.rank)
            print(f"Vorhaben {args.project}/{ini.slug} angelegt (Rang {ini.rank:g}).")
        elif args.initiative_command == "rank":
            ini = board.update_initiative(HUMAN_PRINCIPAL, args.project, args.slug, rank=args.rank)
            print(f"Vorhaben {args.project}/{ini.slug}: Rang {ini.rank:g}.")
        elif args.initiative_command == "assign":
            slug = None if args.slug == "-" else args.slug
            for task in args.tasks:
                ref = task if ("#" in task or "/" in task) else f"{args.project}#{task}"
                moved = board.assign_initiative(HUMAN_PRINCIPAL, ref, slug)
                print(f"{moved.ref} -> {moved.initiative_ref or 'ohne Vorhaben'}  {moved.title}")
        else:
            for ini in board.list_initiatives(args.project):
                print(f"  {args.project}/{ini.slug:<20} Rang {ini.rank:<8g} {ini.title}")
    except BoardError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1
    finally:
        close()
    return 0


def _open_board(config):
    """Board-Dienst auf der konfigurierten Datenbank, wie im Server (api/server.py)."""
    from conclave.api.server import _build_board
    if config.db_provider == "postgres":
        import psycopg2
        conn = psycopg2.connect(config.db_dsn)
        conn.autocommit = True
        from conclave.infrastructure.postgres.schema import initialize_schema
    else:
        from conclave.infrastructure.sqlite.connection import ThreadLocalConnection
        from conclave.infrastructure.sqlite.schema import initialize_schema
        conn = ThreadLocalConnection(config.db_path)
    initialize_schema(conn)
    return _build_board(conn, config), conn.close


def _run_key_rotate(args) -> int:
    """Schluesselwechsel (R13): neuer secret.key, alle Daten neu verschluesselt, alter Schluessel bleibt."""
    from conclave.runtime.key_rotation import KeyRotationError, rotate_secret_key
    from conclave.runtime.paths import get_runtime_paths

    config = ConclaveConfig.from_sources()
    postgres = config.db_provider == "postgres"
    if postgres and args.db:
        print("FEHLER: --db gilt nur fuer SQLite; mit PostgreSQL wird die konfigurierte DSN verwendet.",
              file=sys.stderr)
        return 1
    if postgres:
        import psycopg2
        connection = psycopg2.connect(config.db_dsn)
    else:
        import sqlite3
        connection = sqlite3.connect(str(args.db or config.db_path), timeout=30)
    try:
        count = rotate_secret_key(get_runtime_paths().secret_key_path, connection, postgres=postgres,
                                  drop_old=args.drop_old)
    except KeyRotationError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1
    finally:
        connection.close()
    print(f"Schluessel gewechselt: {count} Werte neu verschluesselt.")
    if args.drop_old:
        print("Abgeloeste Schluessel geloescht; aeltere Backups gelten jetzt als fremd.")
    else:
        print("Der alte Schluessel liegt als secret.key.old-* daneben; er wird fuer aeltere Backups gebraucht.")
    print("Einen laufenden Server danach neu starten.")
    return 0


def _run_token_show(args) -> int:
    """Zeigt Pfad und Einrichtung eines Tokens; den Wert nur mit --reveal (Z5)."""
    from conclave.runtime import api_token

    config = ConclaveConfig.from_sources()
    url = _server_url(config.host, config.port)
    if getattr(args, "reviewer", False):
        return _show_reviewer_token(args, url)
    if not args.agent:
        source = "CONCLAVE_API_KEY" if env_secret("CONCLAVE_API_KEY") else str(api_token.token_path())
        print(f"Mensch-Token: {source}")
        print("Fuer UI, REST-API und CLI. Nie in eine MCP- oder Agent-Konfiguration eintragen.")
        if args.reveal:
            print(api_token.read_token() or "(noch kein Token - Server einmal starten)")
        return 0

    if env_secret("CONCLAVE_AGENT_KEY"):
        token, source = env_secret("CONCLAVE_AGENT_KEY"), "CONCLAVE_AGENT_KEY"
    else:
        path = api_token.agent_token_path()
        existed = path.exists()
        token, source = api_token.load_or_create_agent_token(path), str(path)
        if not existed:
            source += " (neu angelegt)"
    print(f"Agent-Token: {source}")
    print("Hinweis: Setzt der Server CONCLAVE_AGENT_KEY in seiner eigenen Umgebung, gilt nur dieser Wert.")
    print()
    print("MCP-Server in Claude Code einrichten (liest agent.token selbst):")
    print(f"  claude mcp add Conclave -s user -e CONCLAVE_API_URL={url} -- conclave-mcp")
    print()
    print("Oder mit dem Token in der MCP-Konfiguration (anderer Benutzer/Rechner):")
    value = token if args.reveal else "<Inhalt von agent.token>"
    print(f"  claude mcp add Conclave -s user -e CONCLAVE_API_URL={url} -e CONCLAVE_AGENT_KEY={value} -- conclave-mcp")
    if not args.reveal:
        print()
        print("Den Wert zeigt `conclave token show --agent --reveal`.")
    print()
    print("Alte Einrichtungen mit CONCLAVE_API_KEY bitte umstellen: Mit dem Mensch-Token hat ein Agent vollen Zugang.")
    return 0


def _run_migrate_personal(args) -> int:
    from pathlib import Path

    from conclave.application.personal_migration import PersonalMigrationService

    config = ConclaveConfig.from_sources()
    target_path = Path(args.target_path) if args.target_path else config.db_path
    backup_dir = Path(args.backup_dir) if args.backup_dir else None
    try:
        report = PersonalMigrationService().migrate(
            Path(args.source_path),
            target_path,
            backup_dir=backup_dir,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    if getattr(args, "json", False):
        print(json.dumps({"success": True, **report.to_dict()}, indent=2, default=str))
        return 0

    mode = "Dry-Run" if report.dry_run else "Migration"
    print(f"{_ok()} {mode} abgeschlossen.")
    print(f"  Quelle: {report.source_path}")
    print(f"  Ziel:   {report.target_path}")
    if report.backup_path:
        print(f"  Backup: {report.backup_path}")
    if report.copied:
        print("  Uebernommen:")
        for table, count in report.copied.items():
            print(f"    {table}: {count}")
    if report.generated_runs:
        print(f"  Aus Audit erzeugte Runs: {report.generated_runs}")
    if report.ignored:
        print("  Bewusst ignoriert:")
        for table, count in report.ignored.items():
            print(f"    {table}: {count}")
    if report.warnings:
        print("  Hinweise:")
        for warning in report.warnings:
            print(f"    {warning}")
    return 0


def main() -> None:
    from conclave.cli.config import ConfigError
    from conclave.infrastructure.migrations import MigrationError
    try:
        sys.exit(run())
    except ConfigError as exc:
        # Ungueltiger Wert in config.toml (z. B. [ui] mode): Meldung mit Datei statt Traceback (U2)
        from conclave.cli.config import config_error_message
        print(config_error_message(exc), file=sys.stderr)
        sys.exit(1)
    except MigrationError as exc:
        # Kurze Meldung statt Traceback; die Migration ist zurueckgerollt (R1, R15)
        print(f"FEHLER: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
