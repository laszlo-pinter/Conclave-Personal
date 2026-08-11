import json
import sqlite3

from conclave.cli.main import build_parser, run


def _legacy_db(path):
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
        INSERT INTO conversations VALUES ('conv-1', 'active', 'Alt', NULL, '2026-01-01T10:00:00+00:00');
        """
    )
    conn.commit()
    conn.close()


def test_parser_has_migrate_personal():
    parser = build_parser()

    args = parser.parse_args(["migrate-personal", "--from", "old.db", "--to", "new.db", "--dry-run"])

    assert args.command == "migrate-personal"
    assert args.source_path == "old.db"
    assert args.target_path == "new.db"
    assert args.dry_run is True


def test_migrate_personal_cli_outputs_json_report(tmp_path, capsys):
    source = tmp_path / "legacy.db"
    target = tmp_path / "personal.db"
    _legacy_db(source)

    code = run(["--json", "migrate-personal", "--from", str(source), "--to", str(target)])

    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["success"] is True
    assert data["copied"]["conversations"] == 1
    assert data["target_path"] == str(target.resolve())
