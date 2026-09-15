"""The eval runner: ``EvalResult``, suite registration, and isolated storage.

Mirrors :mod:`benchmarks.harness` deliberately — same result shape, same
sequential run-and-report loop, same "a failing case never crashes the run"
policy — so anyone familiar with the benchmark harness already knows how this
one works. It is a separate module (not an extension of ``benchmarks``)
because evals are organized by *capability suite* with labeled datasets, not
by ad-hoc smoke check, and because a suite (e.g. curriculum) needs isolated
storage that the benchmark harness never required.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class EvalResult:
    """Outcome of one named check within a suite."""

    suite: str
    name: str
    passed: bool
    duration_ms: float
    metrics: dict[str, object] = field(default_factory=dict)
    detail: str = ""


Eval = Callable[[], Awaitable[EvalResult]]


def all_evals() -> list[Eval]:
    """Return every registered eval across every capability suite.

    Imported lazily (module bodies, not top-level) so a suite module can import
    from this harness without an import cycle, matching
    :func:`benchmarks.harness.all_benchmarks`.
    """
    from evals.assessment import suite as assessment_suite
    from evals.curriculum import suite as curriculum_suite
    from evals.grammar import suite as grammar_suite
    from evals.regression import suite as regression_suite
    from evals.vocabulary import suite as vocabulary_suite

    return [
        *grammar_suite.SUITE,
        *vocabulary_suite.SUITE,
        *assessment_suite.SUITE,
        *curriculum_suite.SUITE,
        *regression_suite.SUITE,
    ]


async def run_evals(evals: list[Eval] | None = None) -> list[EvalResult]:
    """Run every selected eval sequentially and return their results.

    A raised exception from one eval is captured as a failing result rather
    than aborting the run, so one broken suite doesn't hide the rest.
    """
    selected = evals if evals is not None else all_evals()
    results: list[EvalResult] = []
    for one_eval in selected:
        try:
            results.append(await one_eval())
        except Exception as exc:  # noqa: BLE001 - report failures, don't crash
            results.append(
                EvalResult(
                    suite=getattr(one_eval, "__module__", "unknown"),
                    name=getattr(one_eval, "__name__", "unknown"),
                    passed=False,
                    duration_ms=0.0,
                    detail=f"error: {exc}",
                )
            )
    return results


def format_results(results: list[EvalResult]) -> str:
    """Render results as a compact, human-readable, ASCII-safe table.

    ASCII-only (no unicode arrows/box glyphs) so it also prints cleanly from
    the CLI on Windows cp1252 consoles.
    """
    lines = ["", "Polyglot Swarm - evaluation results", "=" * 64]
    current_suite = None
    for r in results:
        if r.suite != current_suite:
            lines.append(f"-- {r.suite} --")
            current_suite = r.suite
        status = "PASS" if r.passed else "FAIL"
        lines.append(f"  [{status}] {r.name:<32} {r.duration_ms:8.2f} ms")
        if r.metrics:
            lines.append(f"          metrics: {r.metrics}")
        if r.detail:
            lines.append(f"          detail : {r.detail}")
    passed = sum(1 for r in results if r.passed)
    lines.append("-" * 64)
    lines.append(f"{passed}/{len(results)} evals passed")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    """Entry point for ``python -m evals``. Returns a process exit code."""
    results = asyncio.run(run_evals())
    print(format_results(results))
    return 0 if all(r.passed for r in results) else 1


@asynccontextmanager
async def isolated_storage() -> AsyncIterator[Path]:
    """Redirect ``settings`` storage paths to a throwaway temp directory.

    Some suites (curriculum) exercise code that reads/writes the SQLite store
    (due reviews, error patterns, skill beliefs). Evals must never touch a
    developer's real ``./data`` — this context manager points ``src.config.
    settings`` at a fresh temp directory for its duration and restores the
    original paths afterward, mirroring what the pytest ``temp_storage``
    fixtures do for tests but usable outside pytest.
    """
    from src.config import settings

    original = {
        "data_dir": settings.data_dir,
        "db_path": settings.db_path,
        "profiles_dir": settings.profiles_dir,
        "chroma_path": settings.chroma_path,
    }
    tmp_dir = Path(tempfile.mkdtemp(prefix="polyglot-eval-"))
    data_dir = tmp_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    settings.data_dir = str(data_dir)
    settings.db_path = str(data_dir / "polyglot.db")
    settings.profiles_dir = str(data_dir / "profiles")
    settings.chroma_path = str(data_dir / "chroma")
    try:
        yield tmp_dir
    finally:
        for key, value in original.items():
            setattr(settings, key, value)
        shutil.rmtree(tmp_dir, ignore_errors=True)
