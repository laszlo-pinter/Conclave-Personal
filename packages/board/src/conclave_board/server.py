# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Laszlo Pinter

"""Board-Server starten: ``conclave-board serve`` (T1).

Ohne Oberflaeche, nur REST. Die Daten liegen in SQLite (Standard) oder PostgreSQL
(``--dsn`` bzw. ``CONCLAVE_BOARD_DSN``). Im Konfigurationsordner liegen
``secret.key`` und die drei Token-Dateien (``api.token``, ``agent.token``,
``reviewer.token``); sie entstehen beim ersten Start, nur fuer den Benutzer lesbar.
Konten und Tokens pro Person (T4), die CLI fuer Menschen (T6) und der Netzbetrieb
hinter einem Proxy (T7) folgen.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from conclave_board import __version__

DEFAULT_PORT = 8200


def default_config_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "ConclaveBoard"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "conclave-board"


def default_db_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "ConclaveBoard"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "conclave-board"
    return base / "board.db"


def open_board(*, db_path: Path | None = None, dsn: str = "", config_dir: Path | None = None,
               statuses: tuple[str, ...] | None = None):
    """Verbindung, Schema (Migrationsreihe des Boards) und BoardService. Gibt (board, connection) zurueck."""
    from conclave_board.application.board import BoardService
    from conclave_board.domain.board import StatusFlow
    from conclave_board.infrastructure.crypto import CryptoService
    from conclave_board.infrastructure.migrations import run_board_migrations
    from conclave_board.runtime.file_security import make_private_dirs

    config_dir = config_dir or default_config_dir()
    make_private_dirs(config_dir)
    crypto = CryptoService.load_or_generate(config_dir / "secret.key")
    if dsn:
        try:
            import psycopg2
        except ImportError:
            raise SystemExit("PostgreSQL braucht 'psycopg2-binary' (pip install \"conclave-board[postgres]\").") from None
        from conclave_board.infrastructure.postgres.board_repository import PostgresBoardRepository
        connection = psycopg2.connect(dsn)
        connection.autocommit = True
        run_board_migrations(connection, is_postgres=True)
        repo = PostgresBoardRepository(connection, crypto)
    else:
        from conclave_board.infrastructure.sqlite.board_repository import SQLiteBoardRepository
        from conclave_board.infrastructure.sqlite.connection import ThreadLocalConnection
        from conclave_board.runtime.file_security import create_private
        db_path = db_path or default_db_path()
        create_private(db_path)
        connection = ThreadLocalConnection(db_path)
        run_board_migrations(connection, is_postgres=False)
        repo = SQLiteBoardRepository(connection, crypto, autocommit=True)
    board = BoardService(repo, StatusFlow(statuses) if statuses else StatusFlow())
    board.sync_flow()
    return board, connection


def load_auth(config_dir: Path):
    """Drei feste Tokens wie in Personal (bis T4): Mensch, Agent, Reviewer."""
    from conclave_board.infrastructure.auth import StaticKeyAuthService
    from conclave_board.runtime.tokens import AGENT_PREFIX, HUMAN_PREFIX, REVIEWER_PREFIX, create_token_file

    return StaticKeyAuthService(create_token_file(config_dir / "api.token", HUMAN_PREFIX),
                                create_token_file(config_dir / "agent.token", AGENT_PREFIX),
                                create_token_file(config_dir / "reviewer.token", REVIEWER_PREFIX))


def build_app(*, db_path: Path | None = None, dsn: str = "", config_dir: Path | None = None,
              allowed_hosts: str = ""):
    from conclave_board.api.app import create_board_app

    config_dir = config_dir or default_config_dir()
    board, _connection = open_board(db_path=db_path, dsn=dsn, config_dir=config_dir)
    return create_board_app(board, load_auth(config_dir), allowed_hosts=allowed_hosts)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="conclave-board", description="Conclave Board (ohne Oberflaeche)")
    parser.add_argument("--version", action="version", version=f"conclave-board {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Board-Server starten (REST)")
    serve.add_argument("--host", default="127.0.0.1", help="Adresse (Standard 127.0.0.1)")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port (Standard {DEFAULT_PORT})")
    serve.add_argument("--db", type=Path, default=None, help="SQLite-Datei (Standard im Datenordner)")
    serve.add_argument("--dsn", default=os.environ.get("CONCLAVE_BOARD_DSN", ""),
                       help="PostgreSQL-DSN statt SQLite (oder CONCLAVE_BOARD_DSN)")
    serve.add_argument("--config-dir", type=Path, default=None,
                       help="Ordner fuer secret.key und Token-Dateien (Standard im Benutzerprofil)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "serve":
        from conclave_board.infrastructure.log import configure_logging
        configure_logging("INFO")
        app = build_app(db_path=args.db, dsn=args.dsn, config_dir=args.config_dir,
                        allowed_hosts=os.environ.get("CONCLAVE_BOARD_ALLOWED_HOSTS", ""))
        from waitress import serve
        print(f"conclave-board {__version__} auf http://{args.host}:{args.port}", file=sys.stderr)
        serve(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
