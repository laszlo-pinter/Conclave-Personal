# src/conclave/infrastructure/log.py

import json
import logging
import time
from contextlib import contextmanager
from collections.abc import Iterator
from typing import Any

CONCLAVE_PREFIX = "conclave."

# Felder, die nicht ins JSON-Output sollen (Python-interne LogRecord-Attribute)
_INTERNAL_FIELDS = frozenset({
    "name", "msg", "args", "created", "relativeCreated",
    "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "pathname", "filename", "module", "levelno", "levelname",
    "msecs", "thread", "threadName", "process", "processName",
    "taskName", "message",
})

# Erlaubte Extra-Felder — nur diese werden ins JSON geschrieben
_ALLOWED_EXTRA = frozenset({
    "conversation_id", "participant_id", "operation", "duration_ms",
    "model", "method", "path", "status", "provider", "agent_id",
    "success", "error", "groups",
})

# Sensitive Felder — werden als "[REDACTED]" ausgegeben
_SENSITIVE_FIELDS = frozenset({
    "content", "api_key", "api_key_enc", "password", "token",
    "secret", "authorization", "cookie",
})


def get_logger(name: str) -> logging.Logger:
    """Erzeugt einen Logger mit conclave.-Prefix."""
    if not name.startswith(CONCLAVE_PREFIX):
        name = CONCLAVE_PREFIX + name
    return logging.getLogger(name)


class JsonFormatter(logging.Formatter):
    """Formatiert Log-Records als einzeilige JSON-Objekte."""

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        entry: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.message,
        }
        # Extra-Felder: Allowlist + Sensitive-Redaction
        for key, value in record.__dict__.items():
            if key in _INTERNAL_FIELDS or key.startswith("_"):
                continue
            if key in _SENSITIVE_FIELDS:
                entry[key] = "[REDACTED]"
            elif key in _ALLOWED_EXTRA:
                entry[key] = value
            # Unbekannte Felder werden stillschweigend verworfen (PII-Schutz)
        return json.dumps(entry, default=str)


@contextmanager
def request_logger(
    logger: logging.Logger,
    operation: str,
    **extra: Any,
) -> Iterator[None]:
    """Context-Manager, der Start/Ende einer Operation loggt inkl. Dauer."""
    logger.debug(
        "%s start",
        operation,
        extra=extra,
    )
    start = time.monotonic()
    try:
        yield
    except Exception as exc:
        duration_ms = (time.monotonic() - start) * 1000
        logger.error(
            "%s failed: %s",
            operation,
            type(exc).__name__,
            extra={**extra, "duration_ms": duration_ms, "error": type(exc).__name__},
        )
        raise
    else:
        duration_ms = (time.monotonic() - start) * 1000
        logger.debug(
            "%s done in %.1f ms",
            operation,
            duration_ms,
            extra={**extra, "duration_ms": duration_ms},
        )
