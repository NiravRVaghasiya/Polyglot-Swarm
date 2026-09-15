"""Minimal, extensible benchmark harness.

Each benchmark is a coroutine that returns a :class:`BenchmarkResult`. The
runner executes them, times them, and prints a compact table. Later phases
(grammar precision, vocabulary extraction, assessment error, curriculum
coverage, cost/latency) register additional benchmarks here.

In deterministic mode the LLM calls resolve to the fake provider, so this
harness runs offline and its timings reflect the surrounding machinery rather
than model variance.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from src.llm.factory import get_provider
from src.llm.provider import Message


@dataclass
class BenchmarkResult:
    """Outcome of a single benchmark."""

    name: str
    passed: bool
    duration_ms: float
    metrics: dict[str, object] = field(default_factory=dict)
    detail: str = ""


Benchmark = Callable[[], Awaitable[BenchmarkResult]]


async def _bench_provider_latency() -> BenchmarkResult:
    """Round-trip latency of a plain generation through the provider layer."""
    provider = get_provider("primary")
    messages = [
        Message("system", "You are a helpful language tutor."),
        Message("user", "Say hello in Spanish."),
    ]
    start = time.perf_counter()
    reply = await provider.generate(messages, max_tokens=64)
    duration_ms = (time.perf_counter() - start) * 1000
    passed = bool(reply.strip())
    return BenchmarkResult(
        name="provider_latency",
        passed=passed,
        duration_ms=duration_ms,
        metrics={"reply_chars": len(reply)},
        detail=reply[:80],
    )


async def _bench_structured_output() -> BenchmarkResult:
    """The provider layer produces parseable JSON when json_mode is requested."""
    provider = get_provider("fast")
    messages = [
        Message("system", "Extract the vocabulary item."),
        Message("user", "The word is 'mesa'."),
    ]
    start = time.perf_counter()
    raw = await provider.generate(messages, json_mode=True, max_tokens=128)
    duration_ms = (time.perf_counter() - start) * 1000
    try:
        parsed = json.loads(raw)
        passed = isinstance(parsed, dict)
    except json.JSONDecodeError:
        passed = False
        parsed = None
    return BenchmarkResult(
        name="structured_output_parseable",
        passed=passed,
        duration_ms=duration_ms,
        metrics={"valid_json": passed},
        detail=raw[:80],
    )


#: Core registry of benchmarks. Phase-specific benchmarks are added lazily in
#: :func:`all_benchmarks` to avoid import cycles (a benchmark module may import
#: from this harness).
BENCHMARKS: list[Benchmark] = [
    _bench_provider_latency,
    _bench_structured_output,
]


def all_benchmarks() -> list[Benchmark]:
    """Return the full benchmark set, including lazily-loaded phase benchmarks."""
    from benchmarks.calibration_bench import bench_calibration
    from benchmarks.grammar_bench import bench_grammar_precision

    return [*BENCHMARKS, bench_grammar_precision, bench_calibration]


async def run_benchmarks(benchmarks: list[Benchmark] | None = None) -> list[BenchmarkResult]:
    """Run all registered benchmarks sequentially and return their results."""
    selected = benchmarks if benchmarks is not None else all_benchmarks()
    results: list[BenchmarkResult] = []
    for bench in selected:
        try:
            results.append(await bench())
        except Exception as exc:  # noqa: BLE001 - report failures, don't crash
            results.append(
                BenchmarkResult(
                    name=getattr(bench, "__name__", "unknown"),
                    passed=False,
                    duration_ms=0.0,
                    detail=f"error: {exc}",
                )
            )
    return results


def format_results(results: list[BenchmarkResult]) -> str:
    """Render results as a compact, human-readable table."""
    lines = ["", "Polyglot Swarm — benchmark results", "=" * 60]
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        lines.append(f"[{status}] {r.name:<32} {r.duration_ms:8.2f} ms")
        if r.metrics:
            lines.append(f"        metrics: {r.metrics}")
        if r.detail:
            lines.append(f"        detail : {r.detail}")
    passed = sum(1 for r in results if r.passed)
    lines.append("-" * 60)
    lines.append(f"{passed}/{len(results)} benchmarks passed")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    """Entry point for ``python -m benchmarks``. Returns a process exit code."""
    results = asyncio.run(run_benchmarks())
    print(format_results(results))
    return 0 if all(r.passed for r in results) else 1
