"""Phase 21 tests: configurable telemetry (settings.telemetry_enabled) gating
whether the FastAPI lifespan registers the durable model_runs telemetry sink.

Uses `with TestClient(...) as client:` deliberately — only the context-
manager form of TestClient actually runs the FastAPI lifespan (a plain
`TestClient(app)` construction does not), which is what wires up
`model_runs.enable_persistence()`.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.config import settings
from src.llm import telemetry


class TestTelemetryToggle:
    def test_enabled_registers_the_persistence_sink(self, temp_storage, monkeypatch):
        monkeypatch.setattr(settings, "telemetry_enabled", True, raising=False)
        telemetry.clear_sinks()
        from src.api.app import create_app

        with TestClient(create_app()):
            assert telemetry._sinks  # a durable sink was registered
        telemetry.clear_sinks()

    def test_disabled_does_not_register_the_persistence_sink(self, temp_storage, monkeypatch):
        monkeypatch.setattr(settings, "telemetry_enabled", False, raising=False)
        telemetry.clear_sinks()
        from src.api.app import create_app

        with TestClient(create_app()):
            assert telemetry._sinks == []
        telemetry.clear_sinks()

    def test_in_memory_ring_buffer_records_regardless_of_the_toggle(self, monkeypatch):
        # The toggle only gates the durable sink; the in-process buffer used
        # by benchmarks/observability always records.
        monkeypatch.setattr(settings, "telemetry_enabled", False, raising=False)
        telemetry.reset()
        telemetry.record(telemetry.ModelRun(provider="p", tier="fast"))
        assert telemetry.recent()
        telemetry.reset()
