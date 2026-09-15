"""In-process rate limiting for authentication endpoints.

A self-hosted, single-process deployment doesn't need a distributed rate
limiter (Redis-backed, etc.) — a small in-memory fixed-window counter per key
is enough to blunt credential-stuffing and registration-spam against
``/auth/register``/``/auth/login``, which is the concrete risk Phase 21 calls
out ("rate limiting"). This is explicitly NOT suitable for a multi-process
deployment (each process would have its own counters); that is an accepted
trade-off for a local-first product, noted in :mod:`src.security` docs.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field


class RateLimitExceededError(Exception):
    """Raised when a caller has exceeded its rate limit.

    Carries ``retry_after_seconds`` so callers (e.g. a FastAPI dependency) can
    surface a ``Retry-After`` header.
    """

    def __init__(self, retry_after_seconds: float) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"rate limit exceeded; retry after {retry_after_seconds:.1f}s")


@dataclass
class _Window:
    count: int = 0
    window_start: float = 0.0


@dataclass
class RateLimiter:
    """A fixed-window rate limiter: at most ``max_calls`` per ``window_seconds``.

    Keyed by an arbitrary string (e.g. an IP address, a username, or a
    composite of both) so a single limiter instance can serve many independent
    buckets — e.g. one bucket per client IP for the login endpoint.
    """

    max_calls: int
    window_seconds: float
    _windows: dict[str, _Window] = field(default_factory=lambda: defaultdict(_Window))

    def check(self, key: str, *, now: float | None = None) -> None:
        """Record one call for ``key``; raise :class:`RateLimitExceeded` if over budget.

        Args:
            key: The bucket identifier.
            now: Injectable clock (seconds since epoch) for deterministic tests;
                defaults to :func:`time.monotonic`.

        Raises:
            RateLimitExceeded: if this call would exceed ``max_calls`` within
                the current window.
        """
        now = time.monotonic() if now is None else now
        window = self._windows[key]
        elapsed = now - window.window_start
        if elapsed >= self.window_seconds:
            # Window expired: start a fresh one.
            window.window_start = now
            window.count = 0
        if window.count >= self.max_calls:
            retry_after = self.window_seconds - elapsed
            raise RateLimitExceededError(max(0.0, retry_after))
        window.count += 1

    def reset(self, key: str | None = None) -> None:
        """Clear rate-limit state for ``key`` (or every key when ``None``).

        Used by tests, and available for an admin/ops override.
        """
        if key is None:
            self._windows.clear()
        else:
            self._windows.pop(key, None)
