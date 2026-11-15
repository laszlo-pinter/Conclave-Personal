"""R13 (conclave#48): Schluesselwechsel (conclave key rotate).

- Alle verschluesselten Werte werden mit dem neuen Schluessel neu verschluesselt,
  danach ist jeder Wert ohne den alten Schluessel lesbar.
- Der alte Schluessel bleibt als secret.key.old-* erhalten (fuer alte Backups);
  eigene Backups von vor dem Wechsel gelten weiter als eigene.
- Ein abgebrochener Wechsel (secret.key.new liegt noch da) verliert nichts.
"""

import sqlite3

import pytest
from cryptography.fernet import Fernet

from conclave.cli.bootstrap import build_agent_service, build_service
from conclave.cli.config import ConclaveConfig
from conclave.domain.agent import Agent
from conclave.domain.participant import ParticipantType
from conclave.infrastructure.crypto import CryptoService
from conclave.runtime.key_rotation import KeyRotationError, rotate_secret_key


@pytest.fixture
def setup(tmp_path, monkeypatch):
    key_path = tmp_path / "secret.key"
    monkeypatch.setenv("CONCLAVE_SECRET_KEY_FILE", str(key_path))
    monkeypatch.delenv("CONCLAVE_SECRET_KEY", raising=False)
    db = tmp_path / "conclave.db"
    config = ConclaveConfig(db_path=db)
    crypto = CryptoService.load_or_generate(key_path)
    service = build_service(config=config, crypto=crypto)
    conv = service.create_conversation()
    service.register_participant(conv.id, "m1", ParticipantType.MODEL, "M1")
    service.add_user_message(conv.id, "Vertrauliche Frage")
    agents = build_agent_service(config=config, crypto=crypto)
    agents.create_agent(Agent(id="a1", name="A", provider="openai", model="gpt", api_key="sk-geheim-123"))
    return key_path, db, config, conv.id


def _ciphertexts(db):
    conn = sqlite3.connect(db)
    try:
        values = []
        for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            for col in conn.execute(f"PRAGMA table_info('{table}')"):
                values += [v for (v,) in conn.execute(f'SELECT "{col[1]}" FROM "{table}"')
                           if isinstance(v, str) and v.startswith("gAAAAA")]
        return values
    finally:
        conn.close()


def _read_all(key_path, config, conv_id):
    crypto = CryptoService.load_or_generate(key_path)
    service = build_service(config=config, crypto=crypto)
    agents = build_agent_service(config=config, crypto=crypto)
    return ([m.content for m in service.load_conversation(conv_id).messages], agents.get_agent("a1").api_key)


def test_rotation_keeps_all_data(setup):
    key_path, db, config, conv_id = setup
    old_key = key_path.read_bytes()
    before = _ciphertexts(db)
    assert before
    count = rotate_secret_key(key_path, sqlite3.connect(db))
    assert count == len(before)
    assert key_path.read_bytes() != old_key
    assert [p.read_bytes() for p in key_path.parent.glob("secret.key.old-*")] == [old_key]
    new_only = Fernet(key_path.read_bytes().strip())
    assert all(new_only.decrypt(v.encode()) for v in _ciphertexts(db))     # nichts mehr unter dem alten Schluessel
    assert _read_all(key_path, config, conv_id) == (["Vertrauliche Frage"], "sk-geheim-123")


def test_interrupted_rotation_loses_nothing(setup):
    """Abbruch nach dem Neuverschluesseln, vor dem Tausch der Dateien."""
    key_path, db, config, conv_id = setup
    rotate_secret_key(key_path, sqlite3.connect(db), _stop_before_swap=True)
    assert (key_path.parent / "secret.key.new").exists()
    assert _read_all(key_path, config, conv_id) == (["Vertrauliche Frage"], "sk-geheim-123")
    rotate_secret_key(key_path, sqlite3.connect(db))                         # Fortsetzen
    assert not (key_path.parent / "secret.key.new").exists()
    assert _read_all(key_path, config, conv_id) == (["Vertrauliche Frage"], "sk-geheim-123")


def test_rotation_refuses_a_key_from_the_environment(setup, monkeypatch):
    key_path, db, _, _ = setup
    monkeypatch.setenv("CONCLAVE_SECRET_KEY", Fernet.generate_key().decode())
    with pytest.raises(KeyRotationError):
        rotate_secret_key(key_path, sqlite3.connect(db))


def test_own_backup_from_before_the_rotation_still_restores(setup, tmp_path):
    from conclave.runtime.backup import create_backup_archive, load_backup_secret, load_backup_secrets
    from conclave.runtime.backup import restore_backup_archive

    key_path, db, config, conv_id = setup
    ws = tmp_path / "ws"
    ws.mkdir()
    archive = create_backup_archive(db_path=db, workspace_root=ws, backup_dir=tmp_path / "b",
                                    secret=load_backup_secret())
    rotate_secret_key(key_path, sqlite3.connect(db))
    restore_backup_archive(backup_path=archive, db_path=db, workspace_root=ws, backup_dir=tmp_path / "b",
                           secret=load_backup_secrets())
    assert _read_all(key_path, config, conv_id) == (["Vertrauliche Frage"], "sk-geheim-123")


def test_cli_rotate(setup, capsys):
    from conclave.cli.main import run
    key_path, db, config, conv_id = setup
    assert run(["key", "rotate", "--db", str(db)]) == 0
    assert "neu verschluesselt" in capsys.readouterr().out
    assert _read_all(key_path, config, conv_id) == (["Vertrauliche Frage"], "sk-geheim-123")


# ── Nacharbeit aus dem Review (B2, V1, V2) ─────────────────────────────────

def test_key_file_with_newline_signs_and_checks_backups_alike(setup, tmp_path):
    """B2: Signieren und Pruefen normalisieren den Schluessel gleich."""
    from conclave.runtime.backup import (
        create_backup_archive, load_backup_secret, load_backup_secrets, restore_backup_archive)
    key_path, db, config, conv_id = setup
    key_path.write_bytes(key_path.read_bytes().strip() + b"\n")
    ws = tmp_path / "ws2"
    ws.mkdir()
    archive = create_backup_archive(db_path=db, workspace_root=ws, backup_dir=tmp_path / "b2",
                                    secret=load_backup_secret())
    restore_backup_archive(backup_path=archive, db_path=db, workspace_root=ws, backup_dir=tmp_path / "b2",
                           secret=load_backup_secrets())


def test_backup_signed_with_an_unstripped_key_still_counts_as_own(setup, tmp_path):
    """B2: Backups, die der alte Code mit dem Zeilenumbruch signiert hat, bleiben eigene."""
    from conclave.runtime.backup import create_backup_archive, load_backup_secrets, restore_backup_archive
    key_path, db, config, conv_id = setup
    raw = key_path.read_bytes().strip() + b"\n"
    key_path.write_bytes(raw)
    ws = tmp_path / "ws3"
    ws.mkdir()
    archive = create_backup_archive(db_path=db, workspace_root=ws, backup_dir=tmp_path / "b3", secret=raw)
    restore_backup_archive(backup_path=archive, db_path=db, workspace_root=ws, backup_dir=tmp_path / "b3",
                           secret=load_backup_secrets())


def test_rotation_can_drop_old_keys(setup, tmp_path):
    """V1: Nach einem Wechsel wegen Kompromittierung gelten alte Schluessel nicht mehr."""
    from conclave.runtime.backup import (
        ForeignBackupError, create_backup_archive, load_backup_secret, load_backup_secrets, restore_backup_archive)
    key_path, db, config, conv_id = setup
    ws = tmp_path / "ws4"
    ws.mkdir()
    archive = create_backup_archive(db_path=db, workspace_root=ws, backup_dir=tmp_path / "b4",
                                    secret=load_backup_secret())
    rotate_secret_key(key_path, sqlite3.connect(db))
    rotate_secret_key(key_path, sqlite3.connect(db), drop_old=True)
    assert list(key_path.parent.glob("secret.key.old-*")) == []
    assert _read_all(key_path, config, conv_id) == (["Vertrauliche Frage"], "sk-geheim-123")
    with pytest.raises(ForeignBackupError):
        restore_backup_archive(backup_path=archive, db_path=db, workspace_root=ws, backup_dir=tmp_path / "b4",
                               secret=load_backup_secrets())


def test_cli_rejects_db_option_with_postgres(setup, monkeypatch, capsys):
    """V2: --db gilt nur fuer SQLite; mit Postgres klarer Fehler statt stillem Ignorieren."""
    from conclave.cli.main import run
    _, db, _, _ = setup
    monkeypatch.setenv("CONCLAVE_DB_PROVIDER", "postgres")
    monkeypatch.setenv("CONCLAVE_DB_DSN", "postgresql://nicht/genutzt")
    assert run(["key", "rotate", "--db", str(db)]) == 1
    assert "--db" in capsys.readouterr().err


def test_blob_values_do_not_break_the_rotation(setup):
    """V2: Ein BLOB, der wie ein Chiffrat beginnt, wird uebersprungen."""
    key_path, db, config, conv_id = setup
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE extra (data BLOB)")
    conn.execute("INSERT INTO extra VALUES (?)", (b"gAAAAA-kein-text",))
    conn.commit()
    rotate_secret_key(key_path, conn)
    assert _read_all(key_path, config, conv_id) == (["Vertrauliche Frage"], "sk-geheim-123")
