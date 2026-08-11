# tests/api/test_wsgi_factory.py

"""WSGI-Factory fuer Gunicorn/uWSGI Production-Deployment."""

import pytest
pytest.importorskip("flask")

from unittest.mock import patch

from conclave.cli.config import ConclaveConfig


class TestCreateWsgiApp:
    def test_returns_flask_app(self, tmp_path):
        from conclave.api.server import create_wsgi_app
        config = ConclaveConfig(mode="development", db_path=tmp_path / "test.db")
        with patch("conclave.api.server.ConclaveConfig.from_sources", return_value=config):
            app = create_wsgi_app()
        assert app is not None
        assert hasattr(app, "run")  # Flask-App

    def test_refuses_invalid_production_config(self):
        from conclave.api.server import create_wsgi_app
        config = ConclaveConfig(mode="production", api_key="")
        with patch("conclave.api.server.ConclaveConfig.from_sources", return_value=config):
            with pytest.raises(RuntimeError, match="Production"):
                create_wsgi_app()

    def test_production_with_valid_config(self, tmp_path):
        from conclave.api.server import create_wsgi_app
        config = ConclaveConfig(mode="production", api_key="my-key",
                                db_path=tmp_path / "test.db")
        with patch("conclave.api.server.ConclaveConfig.from_sources", return_value=config), \
             patch("conclave.api.server.validate_production_config", return_value=[]):
            app = create_wsgi_app()
        assert app is not None
