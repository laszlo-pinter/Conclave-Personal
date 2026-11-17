"""T2: Verbindungspool und Transaktionen, ohne Datenbank (nachgebaute Verbindungen).

Die Tests gegen ein echtes PostgreSQL stehen in tests/persistence/test_postgres_concurrency.py.
"""

import threading
import time

import pytest

from conclave_board.infrastructure.postgres.pool import (
    ConnectionPool, DirectConnection, PooledConnection, PoolTimeout, as_transactional, pool_size,
)


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.closed = False

    def execute(self, sql, params=()):
        self.conn.log.append((sql, self.conn.autocommit))

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class FakeConn:
    created = 0

    def __init__(self, dsn):
        FakeConn.created += 1
        self.id = FakeConn.created
        self.closed = 0
        self.autocommit = False
        self.log = []
        self.commits = self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = 1


def _pool(size=2, timeout=5.0):
    return ConnectionPool("dsn", size=size, timeout=timeout, connect=FakeConn)


def test_cursor_outside_a_transaction_borrows_and_returns_a_connection():
    pool = _pool(size=1)
    conn = PooledConnection(pool)
    with conn.cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.conn.autocommit is True
    with conn.cursor() as cur:                       # dieselbe Verbindung ist wieder frei
        cur.execute("SELECT 2")
    assert FakeConn.created >= 1 and conn.autocommit is True


def test_transaction_binds_one_connection_and_commits():
    conn = PooledConnection(_pool())
    with conn.transaction() as raw:
        assert conn.in_transaction and not conn.autocommit
        with conn.cursor() as cur:
            assert cur.conn is raw                   # alle Anweisungen auf derselben Verbindung
        with conn.transaction() as inner:            # verschachtelt: dieselbe Transaktion
            assert inner is raw
    assert raw.commits == 1 and raw.autocommit is True and not conn.in_transaction


def test_transaction_rolls_back_on_error():
    conn = PooledConnection(_pool())
    with pytest.raises(RuntimeError):
        with conn.transaction() as raw:
            raise RuntimeError("kaputt")
    assert raw.commits == 0 and raw.rollbacks >= 1


def test_pool_waits_for_a_free_connection():
    pool = _pool(size=1)
    conn = PooledConnection(pool)
    started, done = threading.Event(), threading.Event()

    def other():
        started.set()
        with conn.transaction():
            done.set()

    with conn.transaction():
        worker = threading.Thread(target=other)
        worker.start()
        started.wait(5)
        time.sleep(0.2)
        assert not done.is_set()                     # wartet auf die einzige Verbindung
    worker.join(5)
    assert done.is_set()


def test_pool_gives_up_after_the_timeout():
    pool = _pool(size=1, timeout=0.2)
    first = pool.acquire()
    with pytest.raises(PoolTimeout, match="Keine Datenbankverbindung frei"):
        pool.acquire()
    pool.release(first)
    pool.release(pool.acquire())                     # danach wieder verfuegbar


class BreaksOnTransaction(FakeConn):
    """Verbindung, die beim Wechsel aus dem Autocommit abbricht (Review V2)."""

    def __init__(self, dsn):
        super().__init__(dsn)
        self.armed = True

    def __setattr__(self, name, value):
        if name == "autocommit" and value is False and getattr(self, "armed", False):
            self.closed = 1
            raise RuntimeError("Verbindung abgebrochen")
        super().__setattr__(name, value)


def test_a_connection_failing_at_begin_does_not_cost_a_pool_slot():
    pool = ConnectionPool("dsn", size=1, timeout=0.5, connect=BreaksOnTransaction)
    conn = PooledConnection(pool)
    with pytest.raises(RuntimeError, match="abgebrochen"):
        with conn.transaction():
            pass
    assert not conn.in_transaction
    pool.release(pool.acquire())                     # der einzige Platz ist wieder frei (sonst PoolTimeout)


def test_a_connection_failing_at_checkout_is_discarded():
    calls = []

    class FailsOnce(FakeConn):
        def __setattr__(self, name, value):
            if name == "autocommit" and value is True and not calls:
                calls.append(self)
                raise RuntimeError("kaputt")
            super().__setattr__(name, value)

    pool = ConnectionPool("dsn", size=1, timeout=0.5, connect=FailsOnce)
    connection = pool.acquire()
    assert connection is not calls[0] and calls[0].closed
    pool.release(connection)


def test_broken_connections_are_replaced():
    pool = _pool(size=1)
    first = pool.acquire()
    first.closed = 1                                 # Verbindung abgerissen
    pool.release(first)
    second = pool.acquire()
    assert second is not first and not second.closed
    pool.release(second)


def test_each_thread_has_its_own_transaction():
    conn = PooledConnection(_pool(size=4))
    seen, barrier = [], threading.Barrier(3)

    def work():
        with conn.transaction() as raw:
            barrier.wait(5)
            seen.append(raw)

    threads = [threading.Thread(target=work) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert len({id(raw) for raw in seen}) == 3


def test_direct_connection_serializes_threads():
    raw = FakeConn("dsn")
    conn = DirectConnection(raw)
    order = []
    inside = threading.Event()

    def other():
        with conn.cursor() as cur:
            cur.execute("SELECT 2")
            order.append("other")

    with conn.transaction():
        order.append("tx")
        worker = threading.Thread(target=other)
        worker.start()
        time.sleep(0.2)
        inside.set()
        order.append("tx-end")
    worker.join(5)
    assert order == ["tx", "tx-end", "other"] and raw.commits == 1
    assert as_transactional(conn) is conn and isinstance(as_transactional(FakeConn("x")), DirectConnection)


@pytest.mark.parametrize("raw, expected", [("", 10), ("4", 4)])
def test_pool_size_from_environment(monkeypatch, raw, expected):
    monkeypatch.setenv("CONCLAVE_TEST_POOL", raw)
    assert pool_size("CONCLAVE_TEST_POOL") == expected


@pytest.mark.parametrize("raw", ["0", "-1", "viele"])
def test_invalid_pool_size_is_rejected(monkeypatch, raw):
    monkeypatch.setenv("CONCLAVE_TEST_POOL", raw)
    with pytest.raises(ValueError, match="ganze Zahl ab 1"):
        pool_size("CONCLAVE_TEST_POOL")
