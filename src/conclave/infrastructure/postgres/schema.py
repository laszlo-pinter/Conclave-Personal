# src/conclave/infrastructure/postgres/schema.py

from conclave.infrastructure.migrations import run_migrations


def initialize_schema(connection) -> None:
    """Erstellt alle Tabellen in PostgreSQL (idempotent via IF NOT EXISTS)."""
    with connection.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id         TEXT PRIMARY KEY,
                status     TEXT NOT NULL,
                topic      TEXT NOT NULL DEFAULT '',
                floor      TEXT,
                rules      TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS participants (
                id               TEXT NOT NULL,
                conversation_id  TEXT NOT NULL REFERENCES conversations(id),
                participant_type TEXT NOT NULL,
                name             TEXT NOT NULL,
                created_at       TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (conversation_id, id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id              TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id),
                author_type     TEXT NOT NULL,
                author_id       TEXT,
                content         TEXT NOT NULL,
                sequence        INTEGER NOT NULL,
                created_at      TIMESTAMPTZ NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agents (
                id            TEXT PRIMARY KEY,
                name          TEXT NOT NULL,
                provider      TEXT NOT NULL,
                model         TEXT NOT NULL,
                api_key_enc   TEXT NOT NULL DEFAULT '',
                role          TEXT NOT NULL DEFAULT '',
                topic         TEXT NOT NULL DEFAULT '',
                system_prompt TEXT NOT NULL DEFAULT '',
                preset        TEXT NOT NULL DEFAULT '',
                api_url       TEXT NOT NULL DEFAULT '',
                response_path TEXT NOT NULL DEFAULT '',
                message_format TEXT NOT NULL DEFAULT 'standard',
                created_at    TIMESTAMPTZ NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id              TEXT PRIMARY KEY,
                timestamp       TIMESTAMPTZ NOT NULL,
                operation       TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                participant_id  TEXT NOT NULL,
                provider        TEXT NOT NULL,
                model           TEXT NOT NULL,
                success         BOOLEAN NOT NULL,
                error_message   TEXT,
                user_id         TEXT,
                input_tokens    INTEGER,
                output_tokens   INTEGER
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id              TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id),
                kind            TEXT NOT NULL,
                participants    TEXT NOT NULL,
                started_at      TIMESTAMPTZ NOT NULL,
                finished_at     TIMESTAMPTZ,
                status          TEXT NOT NULL,
                error           TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS usage_records (
                id              TEXT PRIMARY KEY,
                run_id          TEXT NOT NULL REFERENCES runs(id),
                conversation_id TEXT NOT NULL REFERENCES conversations(id),
                participant_id  TEXT NOT NULL,
                provider        TEXT NOT NULL,
                model           TEXT NOT NULL,
                input_tokens    INTEGER,
                output_tokens   INTEGER,
                created_at      TIMESTAMPTZ NOT NULL
            )
        """)
    connection.commit()

    # Migrationen fuer bestehende DBs (fuegt fehlende Spalten hinzu)
    run_migrations(connection, is_postgres=True)
