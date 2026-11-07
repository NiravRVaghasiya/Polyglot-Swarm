"""Process metrics in the Prometheus text format (ADR-0035).

A deliberately small, dependency-free registry: counters, gauges and
fixed-bucket histograms with labels, rendered by ``GET /metrics``. The API
runs as a single process (SQLite single-writer; see
``docs/production/performance-report.md``), so in-process state is the whole
picture. A multi-process deployment would need ``prometheus_client``'s
multiprocess mode instead.

Label values are bounded by construction: HTTP routes use the route
*template* (``/api/v1/sessions/{session_id}/state``), never the raw path,
and no metric carries a user id or any learner content.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable

_LATENCY_BUCKETS = (0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)

LabelKey = tuple[str, ...]


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _labels(names: tuple[str, ...], values: LabelKey, extra: str = "") -> str:
    parts = [f'{n}="{_escape(v)}"' for n, v in zip(names, values, strict=True)]
    if extra:
        parts.append(extra)
    return "{" + ",".join(parts) + "}" if parts else ""


class _Metric:
    kind = "untyped"

    def __init__(self, name: str, help_text: str, labels: tuple[str, ...] = ()) -> None:
        self.name = name
        self.help = help_text
        self.label_names = labels
        self._lock = threading.Lock()

    def _key(self, labels: dict[str, str]) -> LabelKey:
        return tuple(str(labels.get(n, "")) for n in self.label_names)

    def header(self) -> list[str]:
        return [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} {self.kind}"]

    def samples(self) -> list[str]:  # pragma: no cover - overridden
        return []

    def reset(self) -> None:  # pragma: no cover - overridden
        pass


class Counter(_Metric):
    kind = "counter"

    def __init__(self, name: str, help_text: str, labels: tuple[str, ...] = ()) -> None:
        super().__init__(name, help_text, labels)
        self._values: dict[LabelKey, float] = {}

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        key = self._key(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def value(self, **labels: str) -> float:
        return self._values.get(self._key(labels), 0.0)

    def samples(self) -> list[str]:
        with self._lock:
            items = sorted(self._values.items())
        return [f"{self.name}{_labels(self.label_names, k)} {v:g}" for k, v in items]

    def reset(self) -> None:
        with self._lock:
            self._values.clear()


class Gauge(_Metric):
    """A gauge set directly, or computed at scrape time by ``collector``."""

    kind = "gauge"

    def __init__(
        self,
        name: str,
        help_text: str,
        labels: tuple[str, ...] = (),
        collector: Callable[[], Iterable[tuple[dict[str, str], float]]] | None = None,
    ) -> None:
        super().__init__(name, help_text, labels)
        self._values: dict[LabelKey, float] = {}
        self._collector = collector

    def set(self, value: float, **labels: str) -> None:
        with self._lock:
            self._values[self._key(labels)] = value

    def value(self, **labels: str) -> float:
        return self._values.get(self._key(labels), 0.0)

    def samples(self) -> list[str]:
        if self._collector is not None:
            try:
                for labels, value in self._collector():
                    self.set(value, **labels)
            except Exception:  # noqa: BLE001, S110
                pass
        with self._lock:
            items = sorted(self._values.items())
        return [f"{self.name}{_labels(self.label_names, k)} {v:g}" for k, v in items]

    def reset(self) -> None:
        with self._lock:
            self._values.clear()


class Histogram(_Metric):
    kind = "histogram"

    def __init__(
        self,
        name: str,
        help_text: str,
        labels: tuple[str, ...] = (),
        buckets: tuple[float, ...] = _LATENCY_BUCKETS,
    ) -> None:
        super().__init__(name, help_text, labels)
        self.buckets = buckets
        self._counts: dict[LabelKey, list[int]] = {}
        self._sums: dict[LabelKey, float] = {}

    def observe(self, value: float, **labels: str) -> None:
        key = self._key(labels)
        with self._lock:
            counts = self._counts.setdefault(key, [0] * (len(self.buckets) + 1))
            for i, bound in enumerate(self.buckets):
                if value <= bound:
                    counts[i] += 1
            counts[-1] += 1  # +Inf
            self._sums[key] = self._sums.get(key, 0.0) + value

    def count(self, **labels: str) -> int:
        counts = self._counts.get(self._key(labels))
        return counts[-1] if counts else 0

    def samples(self) -> list[str]:
        out: list[str] = []
        with self._lock:
            items = sorted(self._counts.items())
            sums = dict(self._sums)
        for key, counts in items:
            bounds = [f"{b:g}" for b in self.buckets] + ["+Inf"]
            for bound, c in zip(bounds, counts, strict=True):
                le = 'le="' + bound + '"'
                out.append(f"{self.name}_bucket{_labels(self.label_names, key, le)} {c}")
            out.append(f"{self.name}_sum{_labels(self.label_names, key)} {sums[key]:g}")
            out.append(f"{self.name}_count{_labels(self.label_names, key)} {counts[-1]}")
        return out

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()
            self._sums.clear()


class Registry:
    def __init__(self) -> None:
        self._metrics: dict[str, _Metric] = {}

    def register(self, metric: _Metric) -> _Metric:
        self._metrics[metric.name] = metric
        return metric

    def names(self) -> set[str]:
        return set(self._metrics)

    def render(self) -> str:
        lines: list[str] = []
        for metric in self._metrics.values():
            lines += metric.header() + metric.samples()
        return "\n".join(lines) + "\n"

    def reset(self) -> None:
        for metric in self._metrics.values():
            metric.reset()


REGISTRY = Registry()
_START = time.time()


def _counter(name: str, help_text: str, labels: tuple[str, ...] = ()) -> Counter:
    metric = Counter(name, help_text, labels)
    REGISTRY.register(metric)
    return metric


def _histogram(name: str, help_text: str, labels: tuple[str, ...] = ()) -> Histogram:
    metric = Histogram(name, help_text, labels)
    REGISTRY.register(metric)
    return metric


def _gauge(
    name: str,
    help_text: str,
    labels: tuple[str, ...] = (),
    collector: Callable[[], Iterable[tuple[dict[str, str], float]]] | None = None,
) -> Gauge:
    metric = Gauge(name, help_text, labels, collector)
    REGISTRY.register(metric)
    return metric


# --- HTTP --------------------------------------------------------------------
HTTP_REQUESTS = _counter(
    "polyglot_http_requests_total", "HTTP requests by route template and status.",
    ("method", "route", "status"),
)  # fmt: skip
HTTP_LATENCY = _histogram(
    "polyglot_http_request_duration_seconds", "HTTP request latency.", ("method", "route")
)
RATE_LIMITED = _counter(
    "polyglot_rate_limited_total", "Requests rejected by a rate limit.", ("scope",)
)

# --- LLM providers -------------------------------------------------------------
LLM_CALLS = _counter(
    "polyglot_llm_calls_total", "LLM provider attempts by outcome.",
    ("provider", "tier", "outcome"),
)  # fmt: skip
LLM_LATENCY = _histogram(
    "polyglot_llm_latency_seconds", "LLM provider attempt latency.", ("provider", "tier")
)
LLM_COST = _counter(
    "polyglot_llm_cost_usd_total", "Estimated LLM spend (USD).", ("provider", "tier")
)
LLM_TOKENS = _counter(
    "polyglot_llm_tokens_total", "LLM tokens (estimated).", ("provider", "tier", "direction")
)
LLM_FALLBACKS = _counter(
    "polyglot_llm_fallbacks_total",
    "Requests answered by a provider other than the tier's first choice.",
    ("tier", "provider"),
)
LLM_BUDGET_REJECTIONS = _counter(
    "polyglot_llm_budget_rejections_total", "LLM calls refused by a budget.", ("scope",)
)

# --- Learning workflows --------------------------------------------------------
SESSION_EVENTS = _counter(
    "polyglot_session_events_total",
    "Chat-session lifecycle events (started, finalized, recovered, failed, evicted).",
    ("event",),
)
ASSESSMENTS = _counter(
    "polyglot_assessments_total", "Multimodal assessments by kind and status.",
    ("kind", "status"),
)  # fmt: skip
MAINTENANCE_RUNS = _counter(
    "polyglot_maintenance_runs_total", "Maintenance runs by outcome.", ("outcome",)
)


def _active_sessions() -> Iterable[tuple[dict[str, str], float]]:
    from src.api import sessions

    yield {}, float(sessions.active_count())


def _last_backup() -> Iterable[tuple[dict[str, str], float]]:
    from src.ops.backup import last_verified_backup_time

    ts = last_verified_backup_time()
    if ts is not None:
        yield {}, ts


SESSIONS_ACTIVE = _gauge(
    "polyglot_sessions_active", "Chat sessions held in memory.", (), _active_sessions
)
BACKUP_LAST_SUCCESS = _gauge(
    "polyglot_backup_last_success_timestamp_seconds",
    "Unix time of the newest verified backup set.",
    (),
    _last_backup,
)
PROCESS_START = _gauge("polyglot_process_start_time_seconds", "Process start time.")
PROCESS_START.set(_START)
BUILD_INFO = _gauge("polyglot_build_info", "Version and environment.", ("version", "env"))


def render() -> str:
    from src import __version__
    from src.config import settings

    BUILD_INFO.set(1.0, version=__version__, env=settings.app_env)
    return REGISTRY.render()
