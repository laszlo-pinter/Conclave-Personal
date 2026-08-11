# tests/infrastructure/test_pii_filter.py

import json
import logging

import pytest

from conclave.infrastructure.log import JsonFormatter, get_logger


def _format(msg="test", level=logging.INFO, **extra):
    """Helper: LogRecord erstellen, formatieren, JSON parsen."""
    record = logging.LogRecord(
        name="conclave.test", level=level, pathname="test.py",
        lineno=1, msg=msg, args=(), exc_info=None,
    )
    for k, v in extra.items():
        setattr(record, k, v)
    formatter = JsonFormatter()
    return json.loads(formatter.format(record))


class TestSensitiveFieldsRedacted:
    """Sensitive Feldnamen muessen redaktiert werden."""

    def test_content_field_redacted(self):
        parsed = _format(content="Geheimer Inhalt mit PII")
        assert parsed["content"] == "[REDACTED]"

    def test_api_key_field_redacted(self):
        parsed = _format(api_key="sk-secret-12345")
        assert parsed["api_key"] == "[REDACTED]"

    def test_api_key_enc_field_redacted(self):
        parsed = _format(api_key_enc="gAAAAABencrypted...")
        assert parsed["api_key_enc"] == "[REDACTED]"

    def test_password_field_redacted(self):
        parsed = _format(password="hunter2")
        assert parsed["password"] == "[REDACTED]"

    def test_token_field_redacted(self):
        parsed = _format(token="eyJhbGciOi...")
        assert parsed["token"] == "[REDACTED]"

    def test_secret_field_redacted(self):
        parsed = _format(secret="my-secret-value")
        assert parsed["secret"] == "[REDACTED]"

    def test_authorization_field_redacted(self):
        parsed = _format(authorization="Bearer sk-xxx")
        assert parsed["authorization"] == "[REDACTED]"


class TestAllowedFieldsPassThrough:
    """Erlaubte Felder muessen unveraendert durchgereicht werden."""

    def test_conversation_id_passes(self):
        parsed = _format(conversation_id="conv-123")
        assert parsed["conversation_id"] == "conv-123"

    def test_participant_id_passes(self):
        parsed = _format(participant_id="p-456")
        assert parsed["participant_id"] == "p-456"

    def test_duration_ms_passes(self):
        parsed = _format(duration_ms=42.5)
        assert parsed["duration_ms"] == 42.5

    def test_model_passes(self):
        parsed = _format(model="claude-sonnet-4-20250514")
        assert parsed["model"] == "claude-sonnet-4-20250514"

    def test_operation_passes(self):
        parsed = _format(operation="invoke_participant")
        assert parsed["operation"] == "invoke_participant"

    def test_method_passes(self):
        parsed = _format(method="POST")
        assert parsed["method"] == "POST"

    def test_path_passes(self):
        parsed = _format(path="/conversations/c1")
        assert parsed["path"] == "/conversations/c1"

    def test_status_passes(self):
        parsed = _format(status=200)
        assert parsed["status"] == 200


class TestUnknownFieldsDropped:
    """Unbekannte Felder (weder allowed noch sensitive) werden nicht ausgegeben."""

    def test_unknown_field_dropped(self):
        parsed = _format(random_unknown_field="should not appear")
        assert "random_unknown_field" not in parsed

    def test_user_email_dropped(self):
        parsed = _format(user_email="test@example.com")
        assert "user_email" not in parsed


class TestStandardFieldsPresent:
    """Standard-Felder (timestamp, level, logger, message) muessen immer da sein."""

    def test_standard_fields_always_present(self):
        parsed = _format("hello", content="secret", conversation_id="c1")
        assert "timestamp" in parsed
        assert "level" in parsed
        assert "logger" in parsed
        assert "message" in parsed
        assert parsed["message"] == "hello"
