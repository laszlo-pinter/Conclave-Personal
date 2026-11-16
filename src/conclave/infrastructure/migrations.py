# src/conclave/infrastructure/migrations.py
"""Migrationsreihe von Personal (Tabelle ``_migrations``).

Runner, ``Migration`` und ``MigrationError`` liegen im Board-Paket
(``conclave_board.infrastructure.migrations``), ebenso die Migrationsreihe des
Boards. Damit bestehende Datenbanken und aeltere Versionen unveraendert
funktionieren, enthaelt die Liste hier weiter die sechs Board-Migrationen bis
v0.7.0 an ihrem alten Platz (dieselben Objekte); ``_migrations`` bleibt
vollstaendig. Neue Board-Migrationen kommen nur in die Reihe des Boards.

Personal fuehrt beide Reihen aus (``initialize_schema``): erst diese, dann
``run_board_migrations``. Die Board-Reihe uebernimmt die sechs alten
Migrationen aus ``_migrations``, statt sie erneut auszufuehren.
"""

from __future__ import annotations

from conclave_board.infrastructure.migrations import (  # noqa: F401  (alte Namen bleiben hier erreichbar)
    BOARD_MIGRATIONS,
    PERSONAL_TABLE,
    Migration,
    MigrationError,
    _has_column,
    applied_ids,
    ensure_table,
    logger,
    run_board_migrations,
    run_series,
)

_BOARD = {migration.id: migration for migration in BOARD_MIGRATIONS}


# ── Alle Migrationen in chronologischer Reihenfolge ─────────────────────

MIGRATIONS: list[Migration] = [
    Migration(
        id="001_audit_token_columns",
        description="Token-Spalten fuer audit_log",
        columns=(("audit_log", "input_tokens", "INTEGER"), ("audit_log", "output_tokens", "INTEGER")),
    ),
    Migration(
        id="002_conversation_rules",
        description="Rules-Spalte fuer Conversations",
        columns=(("conversations", "rules", "TEXT NOT NULL DEFAULT ''"),),
    ),
    Migration(
        id="003_agent_universal_fields",
        description="UniversalAdapter-Felder fuer Agents",
        columns=(("agents", "preset", "TEXT NOT NULL DEFAULT ''"),
                 ("agents", "api_url", "TEXT NOT NULL DEFAULT ''"),
                 ("agents", "response_path", "TEXT NOT NULL DEFAULT ''"),
                 ("agents", "message_format", "TEXT NOT NULL DEFAULT 'standard'")),
    ),
    Migration(
        id="004_agent_api_key_enc",
        description="Verschluesselte API-Key-Spalte fuer Agents",
        columns=(("agents", "api_key_enc", "TEXT NOT NULL DEFAULT ''"),),
    ),
    Migration(
        id="005_personal_runs",
        description="Personal-Runs und UsageRecords",
        fn=lambda connection, is_postgres: _create_runs_tables(connection, is_postgres),
    ),
    Migration(
        id="006_tool_events",
        description="Tool-Events fuer deterministische Backend-Aktionen",
        fn=lambda connection, is_postgres: _create_tool_events_table(connection, is_postgres),
    ),
    Migration(
        id="007_context_reports",
        description="Kontext-Reports je Modellaufruf (welcher Kontext an den Provider ging)",
        fn=lambda connection, is_postgres: _create_context_reports_table(connection, is_postgres),
    ),
    Migration(
        id="008_agent_max_messages",
        description="Kuerzungslimit pro Agent (NULL = globaler Default, 0 = keine Kuerzung)",
        columns=(("agents", "max_messages", "INTEGER"),),
    ),
    Migration(
        id="009_consultations",
        description="Consultations (Zweitmeinung zu Kanzo-Tickets) und ihre Zustellungen",
        fn=lambda connection, is_postgres: _create_consultations_tables(connection, is_postgres),
    ),
    Migration(
        id="010_consultation_channels",
        description="Consultation-Kanal beschreibt den Zugang: rest -> human, mcp -> agent (E3)",
        statements=("UPDATE consultations SET channel = 'human' WHERE channel = 'rest'",
                    "UPDATE consultations SET channel = 'agent' WHERE channel = 'mcp'"),
    ),
    Migration(
        id="011_message_origin",
        description="Herkunft von User-Nachrichten (human/agent, NULL = unbekannt)",
        columns=(("messages", "origin", "TEXT"),),
    ),
    _BOARD["012_board"],
    Migration(
        id="013_conversation_model_read",
        description="Freigabe je Conversation: Modelle duerfen Dateien per @read lesen (R6)",
        fn=lambda connection, is_postgres: _add_model_read_column(connection, is_postgres),
    ),
    _BOARD["014_board_rank"],
    _BOARD["015_board_history"],
    _BOARD["016_board_review"],
    _BOARD["017_board_control"],
    Migration(
        id="018_consultation_lease",
        description="Consultations: Lease je Lauf statt pauschalem Abbruch beim Start (R10)",
        fn=lambda connection, is_postgres: _add_consultation_lease(connection, is_postgres),
    ),
    Migration(
        id="019_run_origin",
        description="Herkunft je Lauf (human/agent) fuer die Budgets der Agenten (R11)",
        fn=lambda connection, is_postgres: _add_run_origin(connection, is_postgres),
    ),
    _BOARD["020_board_initiatives"],
]








def _add_run_origin(connection, is_postgres: bool) -> None:
    statements = []
    if not _has_column(connection, is_postgres, "runs", "origin"):
        statements.append("ALTER TABLE runs ADD COLUMN origin TEXT")
    statements.append("CREATE INDEX IF NOT EXISTS idx_runs_origin ON runs(origin, started_at)")
    statements.append("CREATE INDEX IF NOT EXISTS idx_runs_conversation_started ON runs(conversation_id, started_at)")
    for statement in statements:
        if is_postgres:
            with connection.cursor() as cur:
                cur.execute(statement)
        else:
            connection.execute(statement)


def _add_consultation_lease(connection, is_postgres: bool) -> None:
    ts = "TIMESTAMPTZ" if is_postgres else "TEXT"
    statements = [f"ALTER TABLE consultations ADD COLUMN {column} {ddl}"
                  for column, ddl in (("owner", "TEXT"), ("lease_until", ts))
                  if not _has_column(connection, is_postgres, "consultations", column)]
    statements.append("CREATE INDEX IF NOT EXISTS idx_consultations_limit "
                      "ON consultations(source, source_ref, channel, created_at)")
    for statement in statements:
        if is_postgres:
            with connection.cursor() as cur:
                cur.execute(statement)
        else:
            connection.execute(statement)










def _add_model_read_column(connection, is_postgres: bool) -> None:
    if _has_column(connection, is_postgres, "conversations", "model_read"):
        return
    definition = "BOOLEAN NOT NULL DEFAULT FALSE" if is_postgres else "INTEGER NOT NULL DEFAULT 0"
    statement = f"ALTER TABLE conversations ADD COLUMN model_read {definition}"
    if is_postgres:
        with connection.cursor() as cur:
            cur.execute(statement)
    else:
        connection.execute(statement)


def _create_runs_tables(connection, is_postgres: bool) -> None:
    if is_postgres:
        with connection.cursor() as cur:
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
    else:
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


def _create_tool_events_table(connection, is_postgres: bool) -> None:
    if is_postgres:
        with connection.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tool_events (
                    id              TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    message_id      TEXT REFERENCES messages(id),
                    run_id          TEXT REFERENCES runs(id),
                    participant_id  TEXT NOT NULL,
                    tool            TEXT NOT NULL,
                    status          TEXT NOT NULL,
                    input_json      TEXT NOT NULL,
                    output_json     TEXT NOT NULL,
                    error           TEXT,
                    created_at      TIMESTAMPTZ NOT NULL
                )
            """)
    else:
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


def _create_context_reports_table(connection, is_postgres: bool) -> None:
    index = "CREATE INDEX IF NOT EXISTS idx_context_reports_message ON context_reports(message_id)"
    if is_postgres:
        with connection.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS context_reports (
                    id              TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    participant_id  TEXT NOT NULL,
                    message_id      TEXT REFERENCES messages(id),
                    run_id          TEXT REFERENCES runs(id),
                    created_at      TIMESTAMPTZ NOT NULL,
                    report_json     TEXT NOT NULL
                )
            """)
            cur.execute(index)
    else:
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
        connection.execute(index)


def _create_consultations_tables(connection, is_postgres: bool) -> None:
    indexes = (
        "CREATE INDEX IF NOT EXISTS idx_consultations_ref ON consultations(source, source_ref, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_consultations_status ON consultations(status)",
        "CREATE INDEX IF NOT EXISTS idx_deliveries_consultation ON consultation_deliveries(consultation_id)",
    )
    if is_postgres:
        with connection.cursor() as cur:
            cur.execute("""
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
                    include_previous BOOLEAN NOT NULL DEFAULT FALSE,
                    status           TEXT NOT NULL,
                    error            TEXT,
                    conversation_id  TEXT,
                    created_at       TIMESTAMPTZ NOT NULL,
                    finished_at      TIMESTAMPTZ
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS consultation_deliveries (
                    id              TEXT PRIMARY KEY,
                    consultation_id TEXT NOT NULL REFERENCES consultations(id),
                    participant_id  TEXT NOT NULL,
                    message_id      TEXT,
                    marker          TEXT NOT NULL,
                    status          TEXT NOT NULL,
                    attempts        INTEGER NOT NULL DEFAULT 0,
                    error           TEXT,
                    delivered_at    TIMESTAMPTZ
                )
            """)
            for index in indexes:
                cur.execute(index)
    else:
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
        for index in indexes:
            connection.execute(index)




# ── Runner ────────────────────────────────────────────────────────────────


# ── Runner (Tabelle _migrations) ────────────────────────────────────────

def _ensure_migrations_table(connection, is_postgres: bool) -> None:
    """Erstellt die _migrations Tracking-Tabelle."""
    ensure_table(connection, is_postgres, PERSONAL_TABLE)


def _get_applied(connection, is_postgres: bool) -> set[str]:
    """Gibt die IDs aller bereits ausgefuehrten Migrationen zurueck."""
    return applied_ids(connection, is_postgres, PERSONAL_TABLE)


def run_migrations(connection, is_postgres: bool = False, migrations: list[Migration] | None = None) -> list[str]:
    """Fuehrt alle ausstehenden Migrationen von Personal aus, jede in einer eigenen Transaktion.

    Returns: Liste der ausgefuehrten Migrations-IDs.
    Raises: MigrationError, wenn eine Migration fehlschlaegt; dann ist sie
        zurueckgerollt, nicht eingetragen, und spaetere laufen nicht.
    """
    return run_series(connection, is_postgres, MIGRATIONS if migrations is None else migrations, PERSONAL_TABLE)
