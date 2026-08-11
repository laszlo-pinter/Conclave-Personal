import sqlite3
from pathlib import Path

import pytest

from conclave.application.personal_migration import PersonalMigrationService
from conclave.infrastructure.sqlite.schema import initialize_schema


def _old_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE conversations (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            topic TEXT NOT NULL DEFAULT '',
            floor TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE participants (
            id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            participant_type TEXT NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (conversation_id, id)
        );
        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            author_type TEXT NOT NULL,
            author_id TEXT,
            content TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE agents (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            api_key_enc TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT '',
            topic TEXT NOT NULL DEFAULT '',
            system_prompt TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE audit_log (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            operation TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            participant_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            success INTEGER NOT NULL,
            error_message TEXT,
            user_id TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER
        );
        CREATE TABLE consent (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL
        );
        CREATE TABLE dpa (
            provider TEXT PRIMARY KEY,
            reference TEXT NOT NULL
        );
        INSERT INTO conversations VALUES ('conv-1', 'active', 'Alt', NULL, '2026-01-01T10:00:00+00:00');
        INSERT INTO participants VALUES ('agent-1', 'conv-1', 'model', 'Agent Eins', '2026-01-01T10:01:00+00:00');
        INSERT INTO messages VALUES ('msg-1', 'conv-1', 'user', NULL, 'Hallo', 1, '2026-01-01T10:02:00+00:00');
        INSERT INTO agents VALUES ('agent-1', 'Agent Eins', 'openai', 'gpt-test', 'encrypted-key', 'writer', '', '', '2026-01-01T10:03:00+00:00');
        INSERT INTO audit_log VALUES ('audit-1', '2026-01-01T10:04:00+00:00', 'invoke_participant', 'conv-1', 'agent-1', 'openai', 'gpt-test', 1, NULL, NULL, 7, 11);
        INSERT INTO consent VALUES ('consent-1', 'conv-1');
        INSERT INTO dpa VALUES ('openai', 'legacy-dpa');
        """
    )
    conn.commit()
    conn.close()


def _count(path: Path, table: str) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_migrate_personal_copies_core_data_and_ignores_compliance(tmp_path):
    source = tmp_path / "legacy.db"
    target = tmp_path / "personal.db"
    _old_db(source)

    report = PersonalMigrationService().migrate(source, target)

    assert report.copied["conversations"] == 1
    assert report.copied["participants"] == 1
    assert report.copied["messages"] == 1
    assert report.copied["agents"] == 1
    assert report.copied["audit_log"] == 1
    assert report.ignored == {"consent": 1, "dpa": 1}
    assert report.generated_runs == 1
    assert _count(target, "runs") == 1
    assert _count(target, "usage_records") == 1


def test_migrate_personal_creates_backup_before_existing_target_changes(tmp_path):
    source = tmp_path / "legacy.db"
    target = tmp_path / "personal.db"
    backup_dir = tmp_path / "backups"
    _old_db(source)
    conn = sqlite3.connect(target)
    initialize_schema(conn)
    conn.close()

    report = PersonalMigrationService().migrate(source, target, backup_dir=backup_dir)

    assert report.backup_path is not None
    assert report.backup_path.parent == backup_dir
    assert report.backup_path.is_file()


def test_migrate_personal_is_idempotent_for_existing_rows(tmp_path):
    source = tmp_path / "legacy.db"
    target = tmp_path / "personal.db"
    _old_db(source)
    service = PersonalMigrationService()

    first = service.migrate(source, target)
    second = service.migrate(source, target)

    assert first.total_copied > 0
    assert second.total_copied == 0
    assert second.skipped["conversations"] == 1
    assert _count(target, "messages") == 1


def test_migrate_personal_dry_run_does_not_create_target(tmp_path):
    source = tmp_path / "legacy.db"
    target = tmp_path / "personal.db"
    _old_db(source)

    report = PersonalMigrationService().migrate(source, target, dry_run=True)

    assert report.dry_run is True
    assert report.copied["conversations"] == 1
    assert not target.exists()


def test_migrate_personal_rejects_same_source_and_target(tmp_path):
    source = tmp_path / "legacy.db"
    _old_db(source)

    with pytest.raises(ValueError, match="Quelle und Ziel"):
        PersonalMigrationService().migrate(source, source)
