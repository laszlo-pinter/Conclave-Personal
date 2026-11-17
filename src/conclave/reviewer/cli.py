"""``conclave-reviewer run``: den Reviewer starten (W1; ``status`` und der Start mit dem Desktop folgen in W4).

    conclave-reviewer run --config <config.toml> [--data-dir <ordner>] [--dry-run] [--once]

Bis W2 liest der Reviewer die ``config.toml`` des alten Watchers. Log, Zustand, Sperre,
MCP-Konfiguration und Worktrees liegen im Datenordner (Standard: der Ordner der config.toml bzw.
``CONCLAVE_REVIEWER_DATA_DIR``). Laeuft der alte Watcher noch, startet der Reviewer nicht.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from conclave.reviewer.lock import AlreadyRunning, ProcessLock
from conclave.reviewer.watch import Reviewer, default_data_dir, legacy_locks, load_config


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="conclave-reviewer", description="Automatischer Reviewer fuer das Board")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Spalte review beobachten und Reviews starten")
    run.add_argument("--config", type=Path, required=True, help="config.toml (bis W2 die des alten Watchers)")
    run.add_argument("--data-dir", type=Path, default=None,
                     help="Ordner fuer Log, Zustand, Sperre und Worktrees (Standard: Ordner der config.toml)")
    run.add_argument("--dry-run", action="store_true",
                     help="nur protokollieren, was liefe (mit Aufruf und MCP-Konfiguration); kein Review")
    run.add_argument("--once", action="store_true", help="einmal abfragen und beenden")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config_path = args.config.resolve()
    cfg = load_config(config_path)
    data_dir = (args.data_dir or default_data_dir(config_path)).resolve()
    reviewer = Reviewer(cfg, data_dir, base_dir=config_path.parent)
    try:
        with ProcessLock(reviewer.lock_file, legacy=legacy_locks(cfg, config_path)):
            reviewer.loop(dry_run=args.dry_run, once=args.once)
    except AlreadyRunning as e:
        print(f"Nicht gestartet: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
