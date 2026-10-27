import sqlite3

from conclave.infrastructure.migrations import run_migrations


def initialize_schema(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = ON")

    connection.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id         TEXT PRIMARY KEY,
            status     TEXT NOT NULL,
            topic      TEXT NOT NULL DEFAULT '',
            floor      TEXT,
            rules      TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS participants (
            id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            participant_type TEXT NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id),
            PRIMARY KEY (conversation_id, id)
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            author_type TEXT NOT NULL,
            author_id TEXT,
            content TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(conversation_id) REFERENCES conversations(id)
        )
    """)

    connection.execute("""
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
            max_messages INTEGER,
            created_at    TEXT NOT NULL
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id              TEXT PRIMARY KEY,
            timestamp       TEXT NOT NULL,
            operation       TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            participant_id  TEXT NOT NULL,
            provider        TEXT NOT NULL,
            model           TEXT NOT NULL,
            success         INTEGER NOT NULL,
            error_message   TEXT,
            user_id         TEXT,
            input_tokens    INTEGER,
            output_tokens   INTEGER
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id              TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            kind            TEXT NOT NULL,
            participants    TEXT NOT NULL,
            started_at      TEXT NOT NULL,
            finished_at     TEXT,
            status          TEXT NOT NULL,
            error           TEXT,
            FOREIGN KEY(conversation_id) REFERENCES conversations(id)
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS usage_records (
            id              TEXT PRIMARY KEY,
            run_id          TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            participant_id  TEXT NOT NULL,
            provider        TEXT NOT NULL,
            model           TEXT NOT NULL,
            input_tokens    INTEGER,
            output_tokens   INTEGER,
            created_at      TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES runs(id),
            FOREIGN KEY(conversation_id) REFERENCES conversations(id)
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS tool_events (
            id              TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            message_id      TEXT,
            run_id          TEXT,
            participant_id  TEXT NOT NULL,
            tool            TEXT NOT NULL,
            status          TEXT NOT NULL,
            input_json      TEXT NOT NULL,
            output_json     TEXT NOT NULL,
            error           TEXT,
            created_at      TEXT NOT NULL,
            FOREIGN KEY(conversation_id) REFERENCES conversations(id),
            FOREIGN KEY(message_id) REFERENCES messages(id),
            FOREIGN KEY(run_id) REFERENCES runs(id)
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS context_reports (
            id              TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            participant_id  TEXT NOT NULL,
            message_id      TEXT,
            run_id          TEXT,
            created_at      TEXT NOT NULL,
            report_json     TEXT NOT NULL,
            FOREIGN KEY(conversation_id) REFERENCES conversations(id),
            FOREIGN KEY(message_id) REFERENCES messages(id),
            FOREIGN KEY(run_id) REFERENCES runs(id)
        )
    """)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_context_reports_message ON context_reports(message_id)"
    )

    connection.execute("""
        CREATE TABLE IF NOT EXISTS consultations (
            id               TEXT PRIMARY KEY,
            source           TEXT NOT NULL,
            source_ref       TEXT NOT NULL,
            question         TEXT NOT NULL,
            reviewers_json   TEXT NOT NULL,
            channel          TEXT NOT NULL,
            mode             TEXT NOT NULL,
            context          TEXT NOT NULL DEFAULT '',
            requested_by     TEXT NOT NULL DEFAULT '',
            include_previous INTEGER NOT NULL DEFAULT 0,
            status           TEXT NOT NULL,
            error            TEXT,
            conversation_id  TEXT,
            created_at       TEXT NOT NULL,
            finished_at      TEXT
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS consultation_deliveries (
            id              TEXT PRIMARY KEY,
            consultation_id TEXT NOT NULL,
            participant_id  TEXT NOT NULL,
            message_id      TEXT,
            marker          TEXT NOT NULL,
            status          TEXT NOT NULL,
            attempts        INTEGER NOT NULL DEFAULT 0,
            error           TEXT,
            delivered_at    TEXT,
            FOREIGN KEY(consultation_id) REFERENCES consultations(id)
        )
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS idx_consultations_ref ON consultations(source, source_ref, created_at)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_consultations_status ON consultations(status)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_deliveries_consultation ON consultation_deliveries(consultation_id)")

    connection.commit()

    # Migrationen fuer bestehende DBs (fuegt fehlende Spalten hinzu)
    run_migrations(connection, is_postgres=False)
