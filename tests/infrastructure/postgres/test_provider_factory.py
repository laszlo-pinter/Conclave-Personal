# tests/infrastructure/postgres/test_provider_factory.py
"""Prüft die Provider-Factory in bootstrap.py."""

import pytest
from unittest.mock import patch, MagicMock


def test_build_unit_of_work_sqlite(tmp_path):
    from conclave.cli.bootstrap import build_unit_of_work
    from conclave.cli.config import ConclaveConfig
    from conclave.infrastructure.sqlite.unit_of_work import SQLiteUnitOfWork

    config = ConclaveConfig(db_provider="sqlite", db_path=tmp_path / "test.db")
    uow = build_unit_of_work(config)
    assert isinstance(uow, SQLiteUnitOfWork)


def test_build_unit_of_work_postgres():
    pytest.importorskip("psycopg2")
    from conclave.cli.bootstrap import build_unit_of_work
    from conclave.cli.config import ConclaveConfig
    from conclave.infrastructure.postgres.unit_of_work import PostgresUnitOfWork

    config = ConclaveConfig(
        db_provider="postgres",
        db_dsn="postgresql://user:pass@localhost/conclave",
    )
    uow = build_unit_of_work(config)
    assert isinstance(uow, PostgresUnitOfWork)


def test_config_default_provider_is_sqlite():
    from conclave.cli.config import ConclaveConfig
    config = ConclaveConfig()
    assert config.db_provider == "sqlite"


def test_config_postgres_dsn():
    from conclave.cli.config import ConclaveConfig
    config = ConclaveConfig(
        db_provider="postgres",
        db_dsn="postgresql://localhost/mydb",
    )
    assert config.db_provider == "postgres"
    assert config.db_dsn == "postgresql://localhost/mydb"
