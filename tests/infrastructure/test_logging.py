# tests/infrastructure/test_logging.py

import json
import logging
import time

import pytest

from conclave.infrastructure.log import get_logger, JsonFormatter, request_logger


class TestGetLogger:
    def test_returns_logger_with_given_name(self):
        logger = get_logger("conclave.test")
        assert logger.name == "conclave.test"

    def test_returns_logger_instance(self):
        logger = get_logger("conclave.test2")
        assert isinstance(logger, logging.Logger)

    def test_logger_has_conclave_prefix(self):
        logger = get_logger("mymodule")
        assert logger.name == "conclave.mymodule"

    def test_logger_already_prefixed(self):
        logger = get_logger("conclave.already")
        assert logger.name == "conclave.already"


class TestJsonFormatter:
    def _make_record(self, msg="test message", level=logging.INFO, **kwargs):
        record = logging.LogRecord(
            name="conclave.test",
            level=level,
            pathname="test.py",
            lineno=1,
            msg=msg,
            args=(),
            exc_info=None,
        )
        for k, v in kwargs.items():
            setattr(record, k, v)
        return record

    def test_formats_as_valid_json(self):
        formatter = JsonFormatter()
        record = self._make_record()
        output = formatter.format(record)
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    def test_includes_timestamp(self):
        formatter = JsonFormatter()
        record = self._make_record()
        parsed = json.loads(formatter.format(record))
        assert "timestamp" in parsed

    def test_includes_level(self):
        formatter = JsonFormatter()
        record = self._make_record(level=logging.WARNING)
        parsed = json.loads(formatter.format(record))
        assert parsed["level"] == "WARNING"

    def test_includes_logger_name(self):
        formatter = JsonFormatter()
        record = self._make_record()
        parsed = json.loads(formatter.format(record))
        assert parsed["logger"] == "conclave.test"

    def test_includes_message(self):
        formatter = JsonFormatter()
        record = self._make_record(msg="hello world")
        parsed = json.loads(formatter.format(record))
        assert parsed["message"] == "hello world"

    def test_includes_extra_fields(self):
        formatter = JsonFormatter()
        record = self._make_record(conversation_id="conv-123", duration_ms=42.5)
        parsed = json.loads(formatter.format(record))
        assert parsed["conversation_id"] == "conv-123"
        assert parsed["duration_ms"] == 42.5

    def test_excludes_internal_log_record_fields(self):
        formatter = JsonFormatter()
        record = self._make_record()
        parsed = json.loads(formatter.format(record))
        assert "pathname" not in parsed
        assert "lineno" not in parsed
        assert "exc_info" not in parsed


class TestRequestLogger:
    def test_returns_context_manager(self):
        logger = get_logger("test.request")
        ctx = request_logger(logger, operation="test_op")
        assert hasattr(ctx, "__enter__")
        assert hasattr(ctx, "__exit__")

    def test_context_manager_logs_start_and_end(self, caplog):
        logger = get_logger("test.request_log")
        logger.setLevel(logging.DEBUG)
        with caplog.at_level(logging.DEBUG, logger="conclave.test.request_log"):
            with request_logger(logger, operation="invoke", conversation_id="c1"):
                pass
        messages = [r.message for r in caplog.records]
        assert any("invoke" in m and "start" in m.lower() for m in messages)
        assert any("invoke" in m and ("end" in m.lower() or "done" in m.lower() or "ms" in m.lower()) for m in messages)

    def test_context_manager_records_duration(self, caplog):
        logger = get_logger("test.duration")
        logger.setLevel(logging.DEBUG)
        with caplog.at_level(logging.DEBUG, logger="conclave.test.duration"):
            with request_logger(logger, operation="slow_op"):
                time.sleep(0.05)
        end_record = [r for r in caplog.records if hasattr(r, "duration_ms")]
        assert len(end_record) >= 1
        assert end_record[0].duration_ms >= 1

    def test_context_manager_passes_extra_fields(self, caplog):
        logger = get_logger("test.extras")
        logger.setLevel(logging.DEBUG)
        with caplog.at_level(logging.DEBUG, logger="conclave.test.extras"):
            with request_logger(logger, operation="invoke", participant_id="p1"):
                pass
        records_with_pid = [r for r in caplog.records if hasattr(r, "participant_id")]
        assert len(records_with_pid) >= 1
        assert records_with_pid[0].participant_id == "p1"

    def test_context_manager_logs_error_on_exception(self, caplog):
        logger = get_logger("test.error")
        logger.setLevel(logging.DEBUG)
        with caplog.at_level(logging.DEBUG, logger="conclave.test.error"):
            with pytest.raises(ValueError):
                with request_logger(logger, operation="fail_op"):
                    raise ValueError("boom")
        error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert len(error_records) >= 1
        assert "ValueError" in error_records[0].message
