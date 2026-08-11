from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from conclave.infrastructure.sqlite.schema import initialize_schema


PERSONAL_TABLES = (
    "conversations",
    "participants",
    "messages",
    "agents",
    "audit_log",
    "runs",
    "usage_records",
)

COMPLIANCE_TABLES = (
    "consent",
    "consents",
    "dpa",
    "dpas",
    "transfer_policy",
    "transfer_policies",
)


@dataclass
class MigrationReport:
    source_path: Path
    target_path: Path
    backup_path: Path | None = None
    copied: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    ignored: dict[str, int] = field(default_factory=dict)
    generated_runs: int = 0
    dry_run: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def total_copied(self) -> int:
        return sum(self.copied.values()) + self.generated_runs

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": str(self.source_path),
            "target_path": str(self.target_path),
            "backup_path": str(self.backup_path) if self.backup_path else None,
            "copied": self.copied,
            "skipped": self.skipped,
            "ignored": self.ignored,
            "generated_runs": self.generated_runs,
            "total_copied": self.total_copied,
            "dry_run": self.dry_run,
            "warnings": self.warnings,
        }


class PersonalMigrationService:
    """Migriert alte lokale SQLite-Daten in das Personal-Schema."""

    def migrate(
        self,
        source_path: Path,
        target_path: Path,
        *,
        backup_dir: Path | None = None,
        dry_run: bool = False,
    ) -> MigrationReport:
        source = source_path.expanduser().resolve()
        target = target_path.expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"Quelldatenbank nicht gefunden: {source}")
        if source == target:
            raise ValueError("Quelle und Ziel duerfen nicht dieselbe Datei sein.")

        report = MigrationReport(source_path=source, target_path=target, dry_run=dry_run)
        source_conn = sqlite3.connect(str(source))
        source_conn.row_factory = sqlite3.Row
        try:
            source_tables = _table_names(source_conn)
            _collect_ignored_tables(source_conn, source_tables, report)
            if dry_run:
                _collect_dry_run_counts(source_conn, source_tables, report)
                return report

            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                report.backup_path = _backup_target(target, backup_dir)

            target_conn = sqlite3.connect(str(target))
            target_conn.row_factory = sqlite3.Row
            try:
                initialize_schema(target_conn)
                _copy_personal_tables(source_conn, target_conn, source_tables, report)
                report.generated_runs = _generate_runs_from_audit(target_conn)
                target_conn.commit()
            except Exception:
                target_conn.rollback()
                raise
            finally:
                target_conn.close()
        finally:
            source_conn.close()

        return report


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {row[0] for row in rows}


def _columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()]


def _count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _collect_ignored_tables(
    connection: sqlite3.Connection,
    source_tables: set[str],
    report: MigrationReport,
) -> None:
    for table in COMPLIANCE_TABLES:
        if table in source_tables:
            report.ignored[table] = _count(connection, table)


def _collect_dry_run_counts(
    connection: sqlite3.Connection,
    source_tables: set[str],
    report: MigrationReport,
) -> None:
    for table in PERSONAL_TABLES:
        if table in source_tables:
            report.copied[table] = _count(connection, table)
    if "audit_log" in source_tables and "runs" not in source_tables:
        report.generated_runs = _count(connection, "audit_log")


def _backup_target(target: Path, backup_dir: Path | None) -> Path:
    backup_root = backup_dir.expanduser().resolve() if backup_dir else target.parent
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_root / f"{target.stem}-pre-personal-migration-{stamp}{target.suffix}"
    shutil.copy2(target, backup_path)
    return backup_path


def _copy_personal_tables(
    source_conn: sqlite3.Connection,
    target_conn: sqlite3.Connection,
    source_tables: set[str],
    report: MigrationReport,
) -> None:
    for table in PERSONAL_TABLES:
        if table not in source_tables:
            continue
        source_columns = _columns(source_conn, table)
        target_columns = _columns(target_conn, table)
        common = [column for column in target_columns if column in source_columns]
        if not common:
            report.warnings.append(f"Tabelle '{table}' hat keine kompatiblen Spalten.")
            continue

        copied = 0
        skipped = 0
        rows = source_conn.execute(
            f"SELECT {', '.join(common)} FROM {table}"
        ).fetchall()
        insert_sql = (
            f"INSERT OR IGNORE INTO {table} ({', '.join(common)}) "
            f"VALUES ({', '.join('?' for _ in common)})"
        )
        for row in rows:
            before = target_conn.total_changes
            try:
                target_conn.execute(insert_sql, [row[column] for column in common])
            except sqlite3.IntegrityError:
                skipped += 1
                continue
            if target_conn.total_changes > before:
                copied += 1
            else:
                skipped += 1
        report.copied[table] = copied
        if skipped:
            report.skipped[table] = skipped


def _generate_runs_from_audit(connection: sqlite3.Connection) -> int:
    if "audit_log" not in _table_names(connection):
        return 0

    generated = 0
    rows = connection.execute(
        """
        SELECT id, timestamp, operation, conversation_id, participant_id,
               provider, model, success, error_message, input_tokens, output_tokens
        FROM audit_log
        ORDER BY timestamp, id
        """
    ).fetchall()
    for row in rows:
        run_id = f"migration:{row['id']}"
        participants = [row["participant_id"]] if row["participant_id"] else []
        before = connection.total_changes
        try:
            connection.execute(
                """
                INSERT OR IGNORE INTO runs (
                    id, conversation_id, kind, participants, started_at,
                    finished_at, status, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    row["conversation_id"],
                    _run_kind(row["operation"]),
                    json.dumps(participants),
                    row["timestamp"],
                    row["timestamp"],
                    "completed" if row["success"] else "failed",
                    row["error_message"],
                ),
            )
        except sqlite3.IntegrityError:
            continue
        if connection.total_changes == before:
            continue
        generated += 1
        connection.execute(
            """
            INSERT OR IGNORE INTO usage_records (
                id, run_id, conversation_id, participant_id, provider,
                model, input_tokens, output_tokens, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{run_id}:usage",
                run_id,
                row["conversation_id"],
                row["participant_id"] or "",
                row["provider"],
                row["model"],
                row["input_tokens"],
                row["output_tokens"],
                row["timestamp"],
            ),
        )
    return generated


def _run_kind(operation: str) -> str:
    op = operation.lower()
    if "auto" in op:
        return "auto_loop"
    if "parallel" in op:
        return "orchestrate"
    if "orchestrate" in op:
        return "orchestrate"
    if "stream" in op:
        return "stream"
    if "judge" in op:
        return "judge"
    return "invoke"
