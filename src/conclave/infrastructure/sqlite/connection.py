# src/conclave/infrastructure/sqlite/connection.py

"""Eine SQLite-Verbindung pro Thread (AP 5 / B6).

Der API-Server bedient Anfragen parallel. Eine gemeinsame Verbindung ueber
alle Threads vermischt Transaktionen (ein Commit in Thread A schliesst die
halbe Arbeit von Thread B ab) und fuehrt unter Last zu Fehlern.
``ThreadLocalConnection`` verhaelt sich fuer die Repositories wie eine
``sqlite3.Connection``, oeffnet aber je Thread eine eigene Verbindung.

- WAL: Leser blockieren Schreiber nicht.
- ``BEGIN IMMEDIATE`` vor Schreibzugriffen: der Schreib-Lock wird sofort
  angefordert, ``busy_timeout`` wartet auf ihn statt mit "database is locked"
  abzubrechen.
- ``foreign_keys`` gilt pro Verbindung und wird daher fuer jede gesetzt.
"""

import sqlite3
import threading
from pathlib import Path

DEFAULT_BUSY_TIMEOUT_MS = 10_000


def connect(path: Path | str, *, busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path), timeout=busy_timeout_ms / 1000, isolation_level="IMMEDIATE")
    connection.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


class ThreadLocalConnection:
    """Proxy mit der Schnittstelle von ``sqlite3.Connection``, eine Verbindung je Thread."""

    def __init__(self, path: Path | str, *, busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS) -> None:
        self._path = str(path)
        self._busy_timeout_ms = busy_timeout_ms
        # threading.local gibt die Verbindung frei, sobald ihr Thread endet
        # (wichtig beim Entwicklungsserver mit einem Thread pro Anfrage).
        self._local = threading.local()
        # WAL ist eine Eigenschaft der Datenbankdatei und muss nur einmal gesetzt werden.
        self._current().execute("PRAGMA journal_mode=WAL")

    @property
    def path(self) -> str:
        return self._path

    def _current(self) -> sqlite3.Connection:
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = connect(self._path, busy_timeout_ms=self._busy_timeout_ms)
            self._local.connection = connection
        return connection

    def execute(self, *args, **kwargs):
        return self._current().execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        return self._current().executemany(*args, **kwargs)

    def executescript(self, *args, **kwargs):
        return self._current().executescript(*args, **kwargs)

    def cursor(self, *args, **kwargs):
        return self._current().cursor(*args, **kwargs)

    def commit(self) -> None:
        self._current().commit()

    def rollback(self) -> None:
        self._current().rollback()

    @property
    def in_transaction(self) -> bool:
        return self._current().in_transaction

    def __enter__(self):
        return self._current().__enter__()

    def __exit__(self, exc_type, exc, tb):
        return self._current().__exit__(exc_type, exc, tb)

    def __getattr__(self, name):
        return getattr(self._current(), name)

    def close(self) -> None:
        """Schliesst die Verbindung des aktuellen Threads."""
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            connection.close()
            self._local.connection = None
