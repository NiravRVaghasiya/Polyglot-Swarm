"""LLM call telemetry — latency, tokens, and cost per model call.

Every model call the routing layer makes produces a :class:`ModelRun` record:
which provider/model served it, for which tier, how long it took, how many
tokens it used, and the estimated cost. Records are:

- logged (``polyglot.telemetry``),
- kept in a bounded in-process ring buffer for quick inspection/benchmarks,
- optionally persisted to the ``model_runs`` table (Phase 2) when a sink is
  registered — so the LLM layer stays decoupled from the DB.

The plan (Phase 17/22) wants every important model decision observable and
cost/latency tracked; this is the seam that makes that possible without
threading a logger through every agent.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("polyglot.telemetry")

#: How many recent runs to keep in memory for inspection.
_RING_SIZE = 1000


@dataclass
class ModelRun:
    """One LLM call's observability record."""

    provider: str
    tier: str | None
    model: str | None = None
    operation: str = "generate"  # generate | generate_structured | stream
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    success: bool = True
    error: str | None = None
    interaction_id: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# Rough per-1K-token USD pricing, used only for estimates. Deliberately
# conservative and easily overridable; not a billing source of truth.
# Keys are matched as a case-insensitive substring of the model name.
_PRICE_PER_1K: dict[str, tuple[float, float]] = {
    # model-name-substring: (input_per_1k, output_per_1k)
    "claude-3-5-haiku": (0.0008, 0.004),
    "claude-3-5-sonnet": (0.003, 0.015),
    "claude-sonnet-4": (0.003, 0.015),
    "claude-3-opus": (0.015, 0.075),
    "gemini-2.0-flash": (0.0001, 0.0004),
    "gemini-1.5-flash": (0.000075, 0.0003),
    "gemini-1.5-pro": (0.00125, 0.005),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4o": (0.0025, 0.01),
    "gpt-4.1": (0.002, 0.008),
}


def estimate_cost(model: str | None, input_tokens: int, output_tokens: int) -> float:
    """Estimate USD cost for a call. Returns 0.0 for local/unknown/free models."""
    if not model:
        return 0.0
    name = model.lower()
    for key, (in_rate, out_rate) in _PRICE_PER_1K.items():
        if key in name:
            return round(input_tokens / 1000 * in_rate + output_tokens / 1000 * out_rate, 6)
    return 0.0  # local (ollama), fake, or unpriced models are treated as free


# A sink is any callable that durably records a run (e.g. the model_runs store).
Sink = Callable[[ModelRun], None]

_runs: deque[ModelRun] = deque(maxlen=_RING_SIZE)
_sinks: list[Sink] = []


def register_sink(sink: Sink) -> None:
    """Register a durable sink for model runs (e.g. the model_runs SQLite store)."""
    if sink not in _sinks:
        _sinks.append(sink)


def clear_sinks() -> None:
    """Remove all registered sinks (used by tests)."""
    _sinks.clear()


def record(run: ModelRun) -> ModelRun:
    """Record a completed model run: log it, buffer it, and fan out to sinks."""
    _runs.append(run)
    level = logging.INFO if run.success else logging.WARNING
    logger.log(
        level,
        "llm run provider=%s tier=%s model=%s op=%s latency=%.1fms tokens=%d cost=$%.5f%s",
        run.provider,
        run.tier,
        run.model,
        run.operation,
        run.latency_ms,
        run.total_tokens,
        run.cost_usd,
        "" if run.success else f" error={run.error!r}",
    )
    for sink in _sinks:
        try:
            sink(run)
        except Exception as exc:  # noqa: BLE001 - telemetry must never break a call
            logger.warning("telemetry sink failed: %s", exc)
    return run


def recent(limit: int = 50) -> list[ModelRun]:
    """Return the most recent recorded runs (newest last)."""
    runs = list(_runs)
    return runs[-limit:]


def reset() -> None:
    """Clear the in-memory ring buffer (used by tests)."""
    _runs.clear()


def summary() -> dict[str, Any]:
    """Aggregate the buffered runs: totals for calls/tokens/cost and mean latency."""
    runs = list(_runs)
    if not runs:
        return {"calls": 0, "tokens": 0, "cost_usd": 0.0, "mean_latency_ms": 0.0, "failures": 0}
    return {
        "calls": len(runs),
        "tokens": sum(r.total_tokens for r in runs),
        "cost_usd": round(sum(r.cost_usd for r in runs), 6),
        "mean_latency_ms": round(sum(r.latency_ms for r in runs) / len(runs), 2),
        "failures": sum(1 for r in runs if not r.success),
    }


class Timer:
    """Context manager that measures elapsed wall-clock time in milliseconds."""

    def __init__(self) -> None:
        self.elapsed_ms: float = 0.0
        self._start = 0.0

    def __enter__(self) -> Timer:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        self.elapsed_ms = (time.perf_counter() - self._start) * 1000
