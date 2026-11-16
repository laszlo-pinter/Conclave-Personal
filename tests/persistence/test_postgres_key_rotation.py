"""R13 (conclave#48): Schluesselwechsel auf PostgreSQL.

Laeuft nur mit ``CONCLAVE_TEST_POSTGRES_DSN`` (wie test_postgres_board.py).
"""

import os

import pytest

DSN = os.environ.get("CONCLAVE_TEST_POSTGRES_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="CONCLAVE_TEST_POSTGRES_DSN nicht gesetzt")

psycopg2 = pytest.importorskip("psycopg2")

from conclave.domain.agent import Agent  # noqa: E402
from conclave.infrastructure.crypto import CryptoService  # noqa: E402
from conclave.runtime.key_rotation import rotate_secret_key  # noqa: E402


@pytest.fixture
def pg():
    conn = psycopg2.connect(DSN)
    conn.autocommit = True                       # wie im Server
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE")
        cur.execute("CREATE SCHEMA public")
    from conclave.infrastructure.postgres.schema import initialize_schema
    initialize_schema(conn)
    yield conn
    conn.close()


def test_rotation_keeps_agent_keys_on_postgres(pg, tmp_path, monkeypatch):
    from conclave.infrastructure.postgres.agent_repository import PostgresAgentRepository

    monkeypatch.delenv("CONCLAVE_SECRET_KEY", raising=False)
    key_path = tmp_path / "secret.key"
    PostgresAgentRepository(pg, CryptoService.load_or_generate(key_path)).save(
        Agent(id="a1", name="A", provider="openai", model="gpt", api_key="sk-geheim-123"))
    with pg.cursor() as cur:
        cur.execute("SELECT api_key_enc FROM agents")
        [(before,)] = cur.fetchall()

    rotation = psycopg2.connect(DSN)                 # eigene Verbindung mit Transaktion, wie die CLI
    try:
        assert rotate_secret_key(key_path, rotation, postgres=True) == 1
    finally:
        rotation.close()

    with pg.cursor() as cur:
        cur.execute("SELECT api_key_enc FROM agents")
        [(after,)] = cur.fetchall()
    assert after != before
    new_only = CryptoService(key_path.read_bytes().strip())
    assert new_only.decrypt(after) == "sk-geheim-123"
    assert PostgresAgentRepository(pg, CryptoService.load_or_generate(key_path)).get("a1").api_key == "sk-geheim-123"
