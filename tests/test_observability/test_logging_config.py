"""Tests for src.observability.logging_config (Phase 23: structured logging).

Verifies the JSON formatter's shape and that configure_logging actually wires
a handler onto the root logger with the requested level/format, without
depending on any real process-level side effects surviving between tests
(each test resets the root logger's handlers afterward).
"""

from __future__ import annotations

import json
import logging

import pytest

from src.observability import logging_config
from src.observability.logging_config import JsonFormatter, configure_logging


@pytest.fixture(autouse=True)
def _restore_root_logger():
    """Snapshot and restore the root logger's handlers/level around each test.

    configure_logging mutates process-global logging state; without this,
    a test in this file could leak a handler/level into unrelated tests
    running later in the same process.
    """
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    original_configured = logging_config._configured
    yield
    root.handlers.clear()
    root.handlers.extend(original_handlers)
    root.setLevel(original_level)
    logging_config._configured = original_configured


class TestJsonFormatter:
    def _record(self, **extra) -> logging.LogRecord:
        record = logging.LogRecord(
            name="polyglot.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )
        for key, value in extra.items():
            setattr(record, key, value)
        return record

    def test_produces_valid_json(self):
        formatted = JsonFormatter().format(self._record())
        payload = json.loads(formatted)  # must not raise
        assert payload["message"] == "hello world"
        assert payload["level"] == "INFO"
        assert payload["logger"] == "polyglot.test"
        assert "timestamp" in payload

    def test_includes_extra_fields(self):
        formatted = JsonFormatter().format(self._record(interaction_id="iid-1", tier="fast"))
        payload = json.loads(formatted)
        assert payload["interaction_id"] == "iid-1"
        assert payload["tier"] == "fast"

    def test_excludes_standard_attrs_from_extra(self):
        formatted = JsonFormatter().format(self._record())
        payload = json.loads(formatted)
        # Standard LogRecord attrs must not leak in as top-level noise beyond
        # the four defined fields.
        assert set(payload) == {"timestamp", "level", "logger", "message"}

    def test_includes_exception_info(self):
        try:
            raise ValueError("boom")
        except ValueError:
            record = logging.LogRecord(
                name="polyglot.test",
                level=logging.ERROR,
                pathname=__file__,
                lineno=1,
                msg="failed",
                args=(),
                exc_info=True,
            )
            import sys

            record.exc_info = sys.exc_info()
        formatted = JsonFormatter().format(record)
        payload = json.loads(formatted)
        assert "ValueError" in payload["exc_info"]
        assert "boom" in payload["exc_info"]


class TestConfigureLogging:
    def test_sets_level_and_adds_a_handler(self):
        configure_logging(level="WARNING", fmt="text")
        root = logging.getLogger()
        assert root.level == logging.WARNING
        assert len(root.handlers) == 1

    def test_json_format_uses_json_formatter(self):
        configure_logging(level="INFO", fmt="json")
        root = logging.getLogger()
        assert isinstance(root.handlers[0].formatter, JsonFormatter)

    def test_text_format_uses_plain_formatter(self):
        configure_logging(level="INFO", fmt="text")
        root = logging.getLogger()
        assert not isinstance(root.handlers[0].formatter, JsonFormatter)

    def test_repeated_calls_do_not_stack_handlers(self):
        configure_logging(level="INFO", fmt="text")
        configure_logging(level="INFO", fmt="text")
        configure_logging(level="INFO", fmt="text")
        assert len(logging.getLogger().handlers) == 1

    def test_reads_defaults_from_settings_when_unspecified(self, monkeypatch):
        from src.config import settings

        monkeypatch.setattr(settings, "log_level", "DEBUG", raising=False)
        monkeypatch.setattr(settings, "log_format", "json", raising=False)

        configure_logging()

        root = logging.getLogger()
        assert root.level == logging.DEBUG
        assert isinstance(root.handlers[0].formatter, JsonFormatter)

    def test_marks_as_configured(self):
        logging_config._configured = False
        configure_logging()
        assert logging_config.is_configured() is True


class TestEnsureConfigured:
    def test_configures_only_if_not_already_configured(self):
        logging_config._configured = False
        logging_config.ensure_configured()
        assert logging_config.is_configured() is True

        root = logging.getLogger()
        handler_before = root.handlers[0]
        logging_config.ensure_configured()  # second call is a no-op
        assert root.handlers[0] is handler_before
