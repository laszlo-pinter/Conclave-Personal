# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Laszlo Pinter

"""Verbindungen zu PostgreSQL fuer mehrere gleichzeitige Nutzer (T2).

Transaktionsmodell: **Jeder Schreibvorgang ist eine Transaktion** (``transaction()``,
in den Repositories ``_tx``). Die Anweisungen darin duerfen weiter CTEs sein;
entscheidend ist, dass Pruefen und Schreiben in derselben Transaktion auf derselben
Verbindung laufen. Nur so wirken Zeilensperren (``SELECT ... FOR UPDATE``).

- ``ConnectionPool``: begrenzte Zahl Verbindungen. Ist keine frei, wartet die Anfrage
  bis zu ``timeout`` Sekunden (statt sofort zu scheitern wie psycopg2.pool).
  Kaputte Verbindungen werden verworfen und bei Bedarf neu aufgebaut.
- ``PooledConnection``: verhaelt sich fuer die Repositories wie eine psycopg2-Verbindung
  im Autocommit. Ausserhalb einer Transaktion leiht sich jeder Cursor eine Verbindung
  und gibt sie beim Schliessen zurueck; jede Anweisung ist dann fuer sich atomar.
  ``transaction()`` bindet eine Verbindung an den Thread, bis Commit oder Rollback;
  verschachtelte Aufrufe schliessen sich der aeusseren Transaktion an.
- ``DirectConnection``: dieselbe Schnittstelle ueber genau einer Verbindung (Tests,
  CLI). Threads werden serialisiert, damit keiner in die Transaktion eines anderen schreibt.

Worker (Consultations, spaeter Webhooks) bekommen so automatisch eigene Verbindungen.
Migrationen laufen nicht ueber den Pool, sondern auf einer eigenen Verbindung
(``dedicated``), weil der Runner selbst ``BEGIN``/``COMMIT`` sendet.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Callable

DEFAULT_POOL_SIZE = 10
DEFAULT_TIMEOUT = 30.0


def pool_size(env_name: str, default: int = DEFAULT_POOL_SIZE) -> int:
    """Poolgroesse aus einer Umgebungsvariable (ganze Zahl ab 1), sonst ``default``."""
    import os
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{env_name} muss eine ganze Zahl ab 1 sein, nicht {raw!r}.") from None
    if value < 1:
        raise ValueError(f"{env_name} muss eine ganze Zahl ab 1 sein, nicht {raw!r}.")
    return value


class PoolTimeout(RuntimeError):
    """Keine Datenbankverbindung frei innerhalb der Wartezeit."""


def _connect_psycopg2(dsn: str):
    import psycopg2
    return psycopg2.connect(dsn)


def _close_quietly(connection) -> None:
    try:
        connection.close()
    except Exception:  # noqa: BLE001
        pass


def _usable(connection) -> bool:
    return not getattr(connection, "closed", 0)


class ConnectionPool:
    """Begrenzter Pool; ``acquire`` wartet, bis eine Verbindung frei ist."""

    def __init__(self, dsn: str, *, size: int = DEFAULT_POOL_SIZE, timeout: float = DEFAULT_TIMEOUT,
                 connect: Callable[[str], object] | None = None) -> None:
        if size < 1:
            raise ValueError("Die Poolgroesse muss mindestens 1 sein.")
        self._dsn = dsn
        self._connect = connect or _connect_psycopg2
        self._size = size
        self._timeout = timeout
        self._slots = threading.BoundedSemaphore(size)
        self._idle: list = []
        self._lock = threading.Lock()
        self._closed = False

    @property
    def size(self) -> int:
        return self._size

    def acquire(self):
        if self._closed:
            raise RuntimeError("Der Verbindungspool ist geschlossen.")
        if not self._slots.acquire(timeout=self._timeout):
            raise PoolTimeout(f"Keine Datenbankverbindung frei nach {self._timeout:.0f} s "
                              f"(Pool mit {self._size} Verbindungen).")
        try:
            while True:
                with self._lock:
                    connection = self._idle.pop() if self._idle else None
                if connection is None:
                    connection = self._connect(self._dsn)
                if _usable(connection):
                    try:
                        connection.autocommit = True
                    except Exception:  # noqa: BLE001 - unbrauchbar: verwerfen, naechste nehmen
                        _close_quietly(connection)
                        continue
                    return connection
        except BaseException:
            self._slots.release()
            raise

    def release(self, connection, *, broken: bool = False) -> None:
        try:
            if not broken and _usable(connection) and not self._closed:
                try:
                    connection.rollback()             # nichts Halbes an den Naechsten weitergeben
                    connection.autocommit = True
                except Exception:  # noqa: BLE001 - dann ist die Verbindung unbrauchbar
                    broken = True
            if broken or self._closed or not _usable(connection):
                try:
                    connection.close()
                except Exception:  # noqa: BLE001
                    pass
            else:
                with self._lock:
                    self._idle.append(connection)
        finally:
            self._slots.release()

    @contextmanager
    def dedicated(self):
        """Eine Verbindung ausserhalb des Pools (Migrationen, Schluesselwechsel)."""
        connection = self._connect(self._dsn)
        connection.autocommit = True
        try:
            yield connection
        finally:
            connection.close()

    def close(self) -> None:
        self._closed = True
        with self._lock:
            idle, self._idle = self._idle, []
        for connection in idle:
            try:
                connection.close()
            except Exception:  # noqa: BLE001
                pass


class _BorrowedCursor:
    """Cursor auf einer geliehenen Verbindung; Schliessen gibt die Verbindung zurueck."""

    def __init__(self, cursor, release: Callable[[bool], None]) -> None:
        self._cursor = cursor
        self._release = release
        self._done = False

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def __iter__(self):
        return iter(self._cursor)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def close(self) -> None:
        if self._done:
            return
        self._done = True
        try:
            self._cursor.close()
        finally:
            self._release(False)


class PooledConnection:
    """Schnittstelle einer psycopg2-Verbindung im Autocommit, getragen von einem Pool."""

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool
        self._local = threading.local()

    @property
    def pool(self) -> ConnectionPool:
        return self._pool

    def _bound(self):
        return getattr(self._local, "connection", None)

    @property
    def autocommit(self) -> bool:
        return self._bound() is None

    @property
    def in_transaction(self) -> bool:
        return self._bound() is not None

    @property
    def closed(self) -> int:
        return 0

    def cursor(self, *args, **kwargs):
        bound = self._bound()
        if bound is not None:
            return bound.cursor(*args, **kwargs)
        connection = self._pool.acquire()
        try:
            cursor = connection.cursor(*args, **kwargs)
        except BaseException:
            self._pool.release(connection, broken=True)
            raise
        return _BorrowedCursor(cursor, lambda broken: self._pool.release(connection, broken=broken))

    @contextmanager
    def transaction(self):
        """Eine Transaktion auf einer Verbindung des Pools; verschachtelt: die aeussere gilt."""
        if self._bound() is not None:
            yield self._bound()
            return
        connection = self._pool.acquire()
        broken = False
        try:
            try:
                connection.autocommit = False      # scheitert z. B. bei einer gerade abgebrochenen Verbindung
            except Exception:
                broken = True
                raise
            self._local.connection = connection
            try:
                yield connection
                connection.commit()
            except BaseException:
                try:
                    connection.rollback()
                except Exception:  # noqa: BLE001 - Verbindung verwerfen, die Ursache bleibt die Meldung
                    broken = True
                raise
        finally:
            self._local.connection = None
            self._pool.release(connection, broken=broken)   # der Platz im Pool geht nie verloren

    def commit(self) -> None:
        """Ausserhalb einer Transaktion ohne Wirkung (Autocommit), innerhalb macht transaction() den Commit."""

    def rollback(self) -> None:
        """Wie commit(): Rollback einer Transaktion macht transaction()."""

    def close(self) -> None:
        self._pool.close()


class DirectConnection:
    """Dieselbe Schnittstelle ueber genau einer Verbindung; Threads laufen nacheinander."""

    def __init__(self, connection) -> None:
        self._connection = connection
        self._lock = threading.RLock()
        self._local = threading.local()
        connection.autocommit = True

    @property
    def raw(self):
        return self._connection

    @property
    def autocommit(self) -> bool:
        return not getattr(self._local, "depth", 0)

    @property
    def in_transaction(self) -> bool:
        return bool(getattr(self._local, "depth", 0))

    @property
    def closed(self) -> int:
        return getattr(self._connection, "closed", 0)

    def cursor(self, *args, **kwargs):
        if getattr(self._local, "depth", 0):
            return self._connection.cursor(*args, **kwargs)
        self._lock.acquire()
        try:
            cursor = self._connection.cursor(*args, **kwargs)
        except BaseException:
            self._lock.release()
            raise
        return _BorrowedCursor(cursor, lambda broken: self._lock.release())

    @contextmanager
    def transaction(self):
        depth = getattr(self._local, "depth", 0)
        if depth:
            self._local.depth = depth + 1
            try:
                yield self._connection
            finally:
                self._local.depth = depth
            return
        with self._lock:
            self._connection.autocommit = False
            self._local.depth = 1
            try:
                yield self._connection
                self._connection.commit()
            except BaseException:
                self._connection.rollback()
                raise
            finally:
                self._local.depth = 0
                self._connection.autocommit = True

    def commit(self) -> None:
        """Ohne Wirkung; den Commit einer Transaktion macht transaction()."""

    def rollback(self) -> None:
        """Ohne Wirkung; den Rollback einer Transaktion macht transaction()."""

    def close(self) -> None:
        self._connection.close()


def as_transactional(connection):
    """Repositories arbeiten mit PooledConnection oder DirectConnection; eine rohe Verbindung wird umhuellt."""
    if hasattr(connection, "transaction"):
        return connection
    return DirectConnection(connection)

