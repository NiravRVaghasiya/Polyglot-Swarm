"""Centralized logging configuration (Phase 23: production reliability).

Before this module existed, every module called ``logging.getLogger("polyglot.
xxx")`` and nothing ever called :func:`logging.basicConfig` (or configured a
handler/formatter at all) — so in a bare Python process (the CLI, the API
server run directly, a background worker) those log records had no handler
and were silently dropped by Python's logging "handler of last resort", or
inherited whatever ad hoc config a hosting process happened to set up.

:func:`configure_logging` is the one place that wires up a root handler, so
every ``polyglot.*`` logger (and anything else in the process) actually
produces visible output, in a shape controlled by
:data:`~src.config.Settings.log_level` / ``log_format``:

- ``log_format="text"`` — human-readable, one line per record (local dev).
- ``log_format="json"`` — one JSON object per line: timestamp, level, logger
  name, message, and any ``extra=`` fields — the shape a log aggregator
  (CloudWatch, Loki, ELK, ...) expects, and what makes structured log SEARCH
  possible in production rather than grepping free text.

Idempotent and safe to call multiple times (e.g. once from the CLI entry
point, once from the API app factory, once at the top of ``tests/conftest.py``
if a test wants to assert on log output) — repeated calls replace the root
handlers rather than stacking duplicates.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

#: Reserved LogRecord attributes that are already part of the standard
#: format — anything else present on the record (from ``extra={...}``) is
#: surfaced as additional JSON fields.
_STANDARD_RECORD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)


class JsonFormatter(logging.Formatter):
    """Formats each log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_ATTRS and key not in payload:
                payload[key] = value
        return json.dumps(payload, default=str, ensure_ascii=False)


_TEXT_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"

_configured = False


def configure_logging(*, level: str | None = None, fmt: str | None = None) -> None:
    """Configure the root logger for the whole process.

    Args:
        level: Log level name (e.g. "INFO"). Defaults to
            ``settings.log_level``.
        fmt: "json" or "text". Defaults to ``settings.log_format``.

    Reads defaults from :mod:`src.config` lazily (not at import time) so
    importing this module never requires the rest of the app to be
    configured, and so tests that monkeypatch ``settings`` before calling this
    see their override take effect.
    """
    from src.config import settings

    resolved_level = (level or settings.log_level).upper()
    resolved_fmt = fmt or settings.log_format

    handler = logging.StreamHandler()
    if resolved_fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(_TEXT_FORMAT))

    root = logging.getLogger()
    root.handlers.clear()  # idempotent: replace, don't stack, on repeated calls
    root.addHandler(handler)
    root.setLevel(resolved_level)

    global _configured
    _configured = True


def is_configured() -> bool:
    """Whether :func:`configure_logging` has run in this process."""
    return _configured


def ensure_configured() -> None:
    """Configure logging with defaults if it has not been configured yet.

    Used at entry points (CLI, API app factory) that want to guarantee logs
    are visible without forcing every caller (including tests, which manage
    their own logging capture) to configure explicitly.
    """
    if not _configured:
        configure_logging()


__all__ = [
    "JsonFormatter",
    "configure_logging",
    "ensure_configured",
    "is_configured",
]
