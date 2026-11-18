"""``conclave-reviewer``: den Reviewer starten und die alte Konfiguration uebernehmen.

    conclave-reviewer run [--data-dir <ordner>] [--dry-run] [--once]
    conclave-reviewer import-config <alte config.toml> [--target <config.toml>] [--yes]
    conclave-reviewer status [--json]

``conclave desktop`` startet ``run`` als Kindprozess mit ``--parent-pid``: Der Reviewer endet, sobald
der Desktop weg ist (W4).

``run`` liest ``[reviewer]`` aus Conclaves ``config.toml`` (W2). Mit ``--config`` gilt noch die alte
Form (die ``config.toml`` des alten Watchers, W1). Log, Zustand, Sperre, MCP-Konfiguration und
Worktrees liegen im Datenordner (Standard ``<Konfigurationsordner von Conclave>/reviewer`` bzw.
``CONCLAVE_REVIEWER_DATA_DIR``), nur fuer den Benutzer. Laeuft der alte Watcher noch, startet der
Reviewer nicht. Ein Probelauf schreibt keinen Zustand.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from conclave.reviewer import config as reviewer_config
from conclave.reviewer.lock import AlreadyRunning, ProcessLock
from conclave.reviewer.watch import Reviewer, default_data_dir, legacy_locks, load_config


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="conclave-reviewer", description="Automatischer Reviewer fuer das Board")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Spalte review beobachten und Reviews starten")
    run.add_argument("--config", type=Path, default=None,
                     help="alte Form: config.toml des alten Watchers (ohne: [reviewer] in Conclaves config.toml)")
    run.add_argument("--data-dir", type=Path, default=None,
                     help="Ordner fuer Log, Zustand, Sperre und Worktrees (Standard: <Konfiguration>/reviewer)")
    run.add_argument("--dry-run", action="store_true",
                     help="nur protokollieren, was liefe (mit Aufruf und MCP-Konfiguration); kein Review")
    run.add_argument("--once", action="store_true", help="einmal abfragen und beenden")
    run.add_argument("--parent-pid", type=int, default=None,
                     help="mit diesem Prozess enden (conclave desktop startet den Reviewer so)")
    status = sub.add_parser("status", help="Laeuft der Reviewer? Ticket, letztes Ergebnis, Reviews je Stunde, claude")
    status.add_argument("--data-dir", type=Path, default=None)
    status.add_argument("--json", action="store_true", help="als JSON")
    imp = sub.add_parser("import-config", help="Projekte und Grenzwerte aus der alten config.toml uebernehmen")
    imp.add_argument("old", type=Path, help="config.toml des alten Watchers")
    imp.add_argument("--target", type=Path, default=None, help="Ziel (Standard: Conclaves config.toml)")
    imp.add_argument("--yes", action="store_true", help="ohne Rueckfrage schreiben")
    return parser


def _ask(text: str) -> bool:
    print(text)
    try:
        return input("So in die Konfiguration schreiben? [j/N] ").strip().lower() in ("j", "ja", "y", "yes")
    except EOFError:
        return False


def _shutdown(reviewer) -> None:
    """Ende mitten im Lauf: erst claude, dann die Worktrees des laufenden Reviews."""
    reviewer.stop_claude()
    try:
        reviewer.drop_worktrees()
    except Exception as e:                              # noqa: BLE001 - der naechste Start raeumt sonst auf
        reviewer.log(f"worktrees not removed on exit: {e}")


def _import(args) -> int:
    target = args.target or reviewer_config.conclave_config_path()
    confirm = (lambda text: (print(text), True)[1]) if args.yes else _ask
    written = reviewer_config.import_config(args.old.resolve(), target, confirm=confirm)
    print(f"[reviewer] in {target} geschrieben." if written else "Nichts geschrieben.")
    return 0


def _run(args) -> int:
    if args.config is not None:                         # alte Form (W1)
        config_path = args.config.resolve()
        cfg = load_config(config_path)
        reviewer = Reviewer(cfg, (args.data_dir or default_data_dir()).resolve(), base_dir=config_path.parent)
        locks = legacy_locks(cfg, config_path)
    else:
        cfg = reviewer_config.load()
        if not cfg["enabled"]:
            print("Reviewer ist abgeschaltet ([reviewer] enabled = false).", file=sys.stderr)
            return 0
        prompt = reviewer_config.prompt_text(cfg)       # ohne Platzhalter kein Start
        reviewer = Reviewer(cfg, (args.data_dir or default_data_dir()).resolve(), prompt=prompt)
        locks = tuple(Path(p) for p in [cfg.get("legacy_lock_file")] if p)
    reviewer.prepare()
    if args.parent_pid:
        from conclave.reviewer.status import watch_parent

        def gone():
            reviewer.log(f"conclave desktop (PID {args.parent_pid}) beendet, Reviewer endet")
            _shutdown(reviewer)                         # claude ueberlebt den Reviewer nicht
            os._exit(0)                                 # das abgebrochene Review gibt der naechste Start frei (W3)
        watch_parent(args.parent_pid, gone)
    if os.name != "nt":                                 # SIGTERM (stop_reviewer): erst claude, dann Ende
        import signal

        def terminated(_sig, _frame):
            _shutdown(reviewer)
            os._exit(0)
        signal.signal(signal.SIGTERM, terminated)
    with ProcessLock(reviewer.lock_file, legacy=locks):
        reviewer.mark_started(args.dry_run)
        if not args.dry_run:
            reviewer.clean_orphans()                    # Reste eines Endes mitten im Review (#98-Review V3)
        reviewer.loop(dry_run=args.dry_run, once=args.once)
    return 0


def _status(args) -> int:
    import json

    from conclave.reviewer.status import collect, format_status
    try:
        cfg = reviewer_config.load()
    except reviewer_config.ConfigError:
        cfg = {}                                        # auch ohne [reviewer]: dann eben "laeuft nicht"
    info = collect(cfg, (args.data_dir or default_data_dir()).resolve())
    print(json.dumps(info, ensure_ascii=False, indent=2) if args.json else format_status(info))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "status":
            return _status(args)
        return _import(args) if args.command == "import-config" else _run(args)
    except AlreadyRunning as e:
        print(f"Nicht gestartet: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
