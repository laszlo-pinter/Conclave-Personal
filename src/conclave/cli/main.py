# src/conclave/cli/main.py

import argparse
import json
import sys

from conclave.cli.bootstrap import build_agent_service, build_registry, build_service, validate_production_config
from conclave.cli.config import ConclaveConfig
from conclave.cli.handler import CLIHandler, CLIResult
from conclave.domain.participant import ParticipantType
from conclave.runtime.browser import open_browser
from conclave.runtime.desktop import prepare_launch_config


def print_result(result: CLIResult, output_json: bool = False) -> None:
    if output_json:
        print(json.dumps({"success": result.success, "message": result.message, **result.data}, indent=2, default=str))
        return

    icon = "✓" if result.success else "✗"
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

    migrate_p = sub.add_parser("migrate-personal", help="Alte lokale SQLite-Daten nach Conclave Personal migrieren")
    migrate_p.add_argument("--from", required=True, dest="source_path", help="Pfad zur alten SQLite-DB")
    migrate_p.add_argument("--to", default=None, dest="target_path", help="Ziel-DB, Default ist die aktive Conclave-DB")
    migrate_p.add_argument("--backup-dir", default=None, dest="backup_dir", help="Ordner fuer das Ziel-DB-Backup")
    migrate_p.add_argument("--dry-run", action="store_true", help="Nur pruefen und Bericht ausgeben")

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
            print(f"\n✗ {e}", file=sys.stderr)
            return 1

    elif args.command == "orchestrate":
        result = handler.orchestrate(args.conversation_id, args.participants)

    elif args.command == "orchestrate-parallel":
        groups = [g.split(",") for g in args.groups]
        result = handler.orchestrate_parallel(args.conversation_id, groups)

    elif args.command == "auto-loop":
        for event in handler.auto_loop(
            args.conversation_id,
            args.participants,
            stop_signal=args.stop_signal,
            max_rounds=args.max_rounds,
        ):
            if output_json:
                print(json.dumps(event, default=str))
            else:
                kind = event.get("event", "?")
                detail = event.get("participant") or event.get("reason") or ""
                print(f"{kind}: {detail}".rstrip())
        return 0

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
                          message_format=args.message_format)
        except ValueError as e:
            print(f"✗ {e}", file=sys.stderr)
            return 1
        result = handler.create_agent(agent)

    elif args.command == "agent-edit":
        from conclave.domain.agent import Agent
        existing = handler.get_agent(args.id)
        from datetime import datetime
        created_at = datetime.fromisoformat(existing.data["created_at"]) if existing.success else None
        # api_key: explizit übergeben oder bestehenden aus DB behalten
        api_key = args.api_key if args.api_key is not None else (
            existing.data.get("api_key", "") if existing.success else ""
        )
        try:
            agent = Agent(id=args.id, name=args.name, provider=args.provider,
                          model=args.model, api_key=api_key,
                          role=args.role, topic=args.topic,
                          system_prompt=args.system_prompt,
                          preset=args.preset, api_url=args.api_url,
                          response_path=args.response_path,
                          message_format=args.message_format,
                          created_at=created_at)
        except ValueError as e:
            print(f"✗ {e}", file=sys.stderr)
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
            print(f"  API-Key:       {'✓ gesetzt' if d.get('api_key_set') else '✗ nicht gesetzt'}")
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


def _run_web(args) -> int:
    config = ConclaveConfig.from_sources()
    url = args.url or _server_url(config.host, config.port)
    open_browser(url)
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

    if should_open_browser:
        import threading
        threading.Timer(1.0, lambda: open_browser(launch.url)).start()
        print(f"Conclave Desktop: {launch.url}")

    from conclave.api.server import _build_app
    app, config = _build_app(launch.config)
    app.run(host=config.host, port=config.port, debug=config.debug)
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
    print(f"✓ {mode} abgeschlossen.")
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
    sys.exit(run())


if __name__ == "__main__":
    main()
