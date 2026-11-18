# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Laszlo Pinter

"""Schluesselwechsel fuer secret.key (R13, ``conclave key rotate``).

Ablauf, an jeder Stelle abbrechbar ohne Datenverlust:

1. Neuen Schluessel als ``secret.key.new`` anlegen (oder den eines begonnenen
   Wechsels weiterverwenden). Ab hier verschluesselt jeder Start mit ihm.
2. In einer Transaktion jeden Wert der Datenbank, der sich mit einem bekannten
   Schluessel entschluesseln laesst, mit dem neuen Schluessel neu verschluesseln.
3. ``secret.key`` wird zu ``secret.key.old-<Zeit>`` (bleibt fuer alte Backups),
   ``secret.key.new`` zu ``secret.key``.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from conclave_board.infrastructure.crypto import key_file_paths, load_key_files
from conclave_board.runtime.env import env_secret
from conclave_board.runtime.file_security import create_exclusive

_FERNET_PREFIX = "gAAAAA"


class KeyRotationError(RuntimeError):
    """Der Schluessel kann so nicht gewechselt werden."""


def rotate_secret_key(key_path: Path, connection, *, postgres: bool = False, drop_old: bool = False,
                      _stop_before_swap: bool = False) -> int:
    """Wechselt den Schluessel; gibt die Zahl der neu verschluesselten Werte zurueck.

    ``drop_old``: alle abgeloesten Schluessel danach loeschen (Wechsel wegen
    Kompromittierung). Aeltere Backups gelten dann als fremd.
    """
    if env_secret("CONCLAVE_SECRET_KEY"):
        raise KeyRotationError("Der Schluessel kommt aus CONCLAVE_SECRET_KEY; dort wechseln.")
    if not key_path.exists() and not key_file_paths(key_path)[0].exists():
        raise KeyRotationError(f"Kein Schluessel unter {key_path}.")

    pending, _ = key_file_paths(key_path)
    create_exclusive(pending, Fernet.generate_key())            # vorhanden: begonnener Wechsel
    current, old = load_key_files(key_path)                     # current = pending
    target = Fernet(current)
    known = MultiFernet([Fernet(k) for k in old] or [target])
    count = _reencrypt(connection, known, target, postgres=postgres)
    if _stop_before_swap:
        return count

    if key_path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        os.replace(key_path, key_path.with_name(f"{key_path.name}.old-{stamp}"))
    os.replace(pending, key_path)
    if drop_old:
        for path in key_file_paths(key_path)[1]:
            path.unlink(missing_ok=True)
    return count


def _reencrypt(connection, known: MultiFernet, target: Fernet, *, postgres: bool) -> int:
    """Alle Textwerte unter einem bekannten Schluessel mit ``target`` neu verschluesseln (eine Transaktion)."""
    mark = "%s" if postgres else "?"
    cursor = connection.cursor()
    count = 0
    try:
        if not postgres:
            cursor.execute("BEGIN IMMEDIATE")
        for table, column in _text_columns(cursor, postgres):
            cursor.execute(f'SELECT DISTINCT "{column}" FROM "{table}" WHERE "{column}" LIKE {mark}',  # nosec B608 - Namen aus dem Schema
                           (_FERNET_PREFIX + "%",))
            for (value,) in cursor.fetchall():
                if not isinstance(value, str):
                    continue                                    # BLOB o. ae.: nie ein Chiffrat von Conclave
                try:
                    plain = known.decrypt(value.encode())
                except InvalidToken:
                    continue                                    # schon neu oder kein Chiffrat
                cursor.execute(f'UPDATE "{table}" SET "{column}" = {mark} WHERE "{column}" = {mark}',  # nosec B608
                               (target.encrypt(plain).decode(), value))
                count += cursor.rowcount
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        cursor.close()
    return count


def _text_columns(cursor, postgres: bool) -> list[tuple[str, str]]:
    if postgres:
        cursor.execute("SELECT table_name, column_name FROM information_schema.columns "
                       "WHERE table_schema = current_schema() AND data_type IN ('text', 'character varying')")
        return list(cursor.fetchall())
    cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
    columns = []
    for (table,) in cursor.fetchall():
        cursor.execute(f'PRAGMA table_info("{table}")')
        columns += [(table, row[1]) for row in cursor.fetchall()]
    return columns
