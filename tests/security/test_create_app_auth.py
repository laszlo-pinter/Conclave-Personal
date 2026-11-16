"""R15 (conclave#50): create_app ohne Anmeldung nur ausdruecklich (Tests)."""

from unittest.mock import MagicMock

import pytest

pytest.importorskip("flask")

from conclave.api.app import create_app  # noqa: E402


def test_create_app_without_auth_fails():
    with pytest.raises(ValueError, match="auth_service"):
        create_app(MagicMock())


def test_create_app_without_auth_only_when_explicitly_allowed():
    app = create_app(MagicMock(), allow_unauthenticated=True)
    app.config["TESTING"] = True
    assert app.test_client().get("/health").status_code == 200


def test_production_server_passes_auth(tmp_path):
    from conclave.api.server import _build_app
    from conclave.cli.config import ConclaveConfig
    app, _ = _build_app(ConclaveConfig(db_path=tmp_path / "c.db", api_key="cvh_x", agent_api_key="cva_y"))
    assert app.test_client().get("/settings").status_code == 401


def test_cli_reports_a_failed_migration_briefly(monkeypatch, capsys):
    """Eine fehlgeschlagene Migration bricht die CLI mit kurzer Meldung ab, ohne Traceback."""
    from conclave.cli import main as cli
    from conclave.infrastructure.migrations import MigrationError

    def broken(argv=None):
        raise MigrationError("999_x", None, OSError("Platte voll"))

    monkeypatch.setattr(cli, "run", broken)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("FEHLER: Migration 999_x") and "Traceback" not in err
