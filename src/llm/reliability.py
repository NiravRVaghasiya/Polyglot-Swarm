"""Per-provider circuit breaker for the LLM routing layer (Phase 23).

Retrying the *same* dead provider forever on every single call (which is what
:class:`~src.llm.factory.RoutingProvider` did before this module existed) is
wasteful: a provider that is down stays down for more than one call, so paying
its full latency/timeout cost on every subsequent turn just to fail over again
burns time users feel directly. A circuit breaker remembers repeated failures
*across* calls (keyed by provider name, since a fresh provider instance is
built on every :func:`~src.llm.factory.get_provider` call) and skips a
known-bad provider for a cooldown window instead of retrying it immediately.

This mirrors the shape of :class:`~src.security.rate_limit.RateLimiter` — a
small in-process, dependency-free state machine keyed by an arbitrary string,
with an injectable clock for deterministic tests.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class _BreakerState:
    consecutive_failures: int = 0
    opened_at: float | None = None


class CircuitBreaker:
    """Tracks consecutive failures per key and "opens" after a threshold.

    States (per key):

    - **Closed** (default): calls are allowed; failures accumulate.
    - **Open**: after ``failure_threshold`` consecutive failures, the key is
      blocked for ``cooldown_seconds`` — :meth:`allow` returns ``False``.
    - **Half-open**: once the cooldown elapses, :meth:`allow` returns ``True``
      again for a single trial call. A success (:meth:`record_success`) fully
      closes the breaker (clears state); a failure re-opens it and restarts
      the cooldown.
    """

    def __init__(self, *, failure_threshold: int = 3, cooldown_seconds: float = 30.0) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._states: dict[str, _BreakerState] = {}

    def allow(self, key: str, *, now: float | None = None) -> bool:
        """Whether a call for ``key`` should be attempted right now."""
        state = self._states.get(key)
        if state is None or state.opened_at is None:
            return True
        now = time.monotonic() if now is None else now
        return (now - state.opened_at) >= self.cooldown_seconds

    def record_success(self, key: str) -> None:
        """A call for ``key`` succeeded — fully close the breaker."""
        self._states.pop(key, None)

    def record_failure(self, key: str, *, now: float | None = None) -> None:
        """A call for ``key`` failed — accumulate toward opening the breaker."""
        now = time.monotonic() if now is None else now
        state = self._states.setdefault(key, _BreakerState())
        state.consecutive_failures += 1
        if state.consecutive_failures >= self.failure_threshold:
            state.opened_at = now

    def is_open(self, key: str, *, now: float | None = None) -> bool:
        """Whether ``key`` is currently blocked (the inverse of :meth:`allow`)."""
        return not self.allow(key, now=now)

    def reset(self, key: str | None = None) -> None:
        """Clear breaker state for ``key`` (or every key when ``None``).

        Used by tests and available as an ops override to force-close a
        breaker without waiting out the cooldown.
        """
        if key is None:
            self._states.clear()
        else:
            self._states.pop(key, None)


def backoff_delay(attempt: int, *, base_delay: float, max_delay: float) -> float:
    """Exponential backoff delay (seconds) for the given zero-based ``attempt``.

    ``attempt=0`` is the delay before the *first* retry (i.e. after the initial
    attempt has already failed once). Deliberately deterministic (no jitter)
    so tests can assert exact delays; a busy production deployment tuning this
    further can add jitter at the call site.
    """
    return min(max_delay, base_delay * (2.0**attempt))


@dataclass
class RetryPolicy:
    """Bounded retry-with-backoff configuration for a single provider attempt.

    ``max_retries=0`` (the default) preserves the original behavior — one
    attempt per provider, then immediate failover to the next — so existing
    callers that construct a routing chain without configuring retries are
    unaffected.
    """

    max_retries: int = 0
    base_delay: float = 0.2
    max_delay: float = 2.0

    def delay_for(self, attempt: int) -> float:
        return float(backoff_delay(attempt, base_delay=self.base_delay, max_delay=self.max_delay))


#: Shared breaker instance for the real (non-deterministic) provider chain.
#: Module-level because src.llm.factory.get_provider builds a fresh
#: RoutingProvider (and fresh concrete provider instances) on every call —
#: only a state keyed by the stable provider *name* and living outside any
#: single RoutingProvider instance can remember failures across calls.
default_circuit_breaker = CircuitBreaker()


__all__ = [
    "CircuitBreaker",
    "RetryPolicy",
    "backoff_delay",
    "default_circuit_breaker",
]
