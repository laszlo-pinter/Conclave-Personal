# src/conclave/infrastructure/log.py

import json
import logging
import time
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
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
    "success", "error", "groups", "message_id", "run_id",
    "tool_event_id", "tool", "tool_path",
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


def configure_logging(level: str = "INFO", log_file: str | Path | None = None) -> logging.Logger:
    """Konfiguriert Conclave-Logging fuer Server-Runtimes."""
    logger = logging.getLogger("conclave")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    for handler in list(logger.handlers):
        if getattr(handler, "_conclave_managed", False):
            logger.removeHandler(handler)
            handler.close()

    if log_file is not None:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(JsonFormatter())
        handler.setLevel(logger.level)
        handler._conclave_managed = True  # type: ignore[attr-defined]
        logger.addHandler(handler)

    return logger


LOG_FILE_NAME = "conclave-server.log"
_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


def active_log_file() -> Path | None:
    """Pfad der von configure_logging eingerichteten Logdatei, sonst None."""
    for handler in logging.getLogger("conclave").handlers:
        if getattr(handler, "_conclave_managed", False) and isinstance(handler, logging.FileHandler):
            return Path(handler.baseFilename)
    return None


def read_log_tail(path: Path, limit: int = 200, min_level: str = "DEBUG",
                  max_bytes: int = 2 * 1024 * 1024) -> list[dict]:
    """Letzte Eintraege einer JSON-Logdatei, aelteste zuerst.

    Liest hoechstens max_bytes vom Dateiende; Zeilen ohne JSON werden als
    Level "RAW" geliefert und vom Level-Filter nicht ausgeschlossen.
    """
    threshold = _LEVELS.get(min_level.upper(), 0)
    with open(path, "rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - max_bytes))
        data = handle.read()
    lines = data.decode("utf-8", errors="replace").splitlines()
    if size > max_bytes and lines:
        lines = lines[1:]  # erste Zeile ist vermutlich abgeschnitten
    entries: list[dict] = []
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            if not isinstance(entry, dict):
                raise ValueError
        except ValueError:
            entry = {"level": "RAW", "message": line}
        if _LEVELS.get(str(entry.get("level", "")).upper(), threshold) < threshold:
            continue
        entries.append(entry)
        if len(entries) >= limit:
            break
    return list(reversed(entries))


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
