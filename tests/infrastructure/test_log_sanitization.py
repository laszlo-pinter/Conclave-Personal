# tests/infrastructure/test_log_sanitization.py

"""Exception-Texte duerfen keine PII in Logs leaken."""

import logging

import pytest

from conclave.infrastructure.log import get_logger, request_logger


class TestRequestLoggerSanitization:
    def test_exception_message_not_in_log(self, caplog):
        """PII aus Exception darf nicht im Log-Text erscheinen."""
        lgr = get_logger("test.sanitize1")
        lgr.setLevel(logging.DEBUG)
        with caplog.at_level(logging.DEBUG, logger="conclave.test.sanitize1"):
            with pytest.raises(ValueError):
                with request_logger(lgr, operation="test_op"):
                    raise ValueError("user@example.com hat einen Fehler verursacht")

        error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert len(error_records) >= 1
        # PII darf NICHT im Log-Text stehen
        assert "user@example.com" not in error_records[0].message

    def test_exception_type_is_logged(self, caplog):
        """Der Exception-Typ soll geloggt werden."""
        lgr = get_logger("test.sanitize2")
        lgr.setLevel(logging.DEBUG)
        with caplog.at_level(logging.DEBUG, logger="conclave.test.sanitize2"):
            with pytest.raises(RuntimeError):
                with request_logger(lgr, operation="test_op"):
                    raise RuntimeError("secret internal detail")

        error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert "RuntimeError" in error_records[0].message
        assert "secret internal detail" not in error_records[0].message

    def test_conclave_error_type_logged(self, caplog):
        """Conclave-Exceptions loggen nur Typ-Name."""
        from conclave.domain.errors import ConclaveError
        lgr = get_logger("test.sanitize3")
        lgr.setLevel(logging.DEBUG)
        with caplog.at_level(logging.DEBUG, logger="conclave.test.sanitize3"):
            with pytest.raises(ConclaveError):
                with request_logger(lgr, operation="test_op"):
                    raise ConclaveError("sensitive@example.com")

        error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert "ConclaveError" in error_records[0].message
        assert "sensitive@example.com" not in error_records[0].message

    def test_success_log_unchanged(self, caplog):
        """Erfolgreiche Operation loggt wie gewohnt."""
        lgr = get_logger("test.sanitize4")
        lgr.setLevel(logging.DEBUG)
        with caplog.at_level(logging.DEBUG, logger="conclave.test.sanitize4"):
            with request_logger(lgr, operation="my_op"):
                pass

        messages = [r.message for r in caplog.records]
        assert any("my_op" in m and "done" in m.lower() for m in messages)
