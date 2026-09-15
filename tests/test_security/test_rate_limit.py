"""Phase 21 tests: the in-process fixed-window rate limiter."""

from __future__ import annotations

import pytest

from src.security.rate_limit import RateLimiter, RateLimitExceededError


class TestRateLimiter:
    def test_allows_up_to_max_calls(self):
        limiter = RateLimiter(max_calls=3, window_seconds=60.0)
        for _ in range(3):
            limiter.check("key", now=0.0)  # must not raise

    def test_raises_after_max_calls(self):
        limiter = RateLimiter(max_calls=3, window_seconds=60.0)
        for _ in range(3):
            limiter.check("key", now=0.0)
        with pytest.raises(RateLimitExceededError):
            limiter.check("key", now=0.0)

    def test_retry_after_is_positive_and_bounded(self):
        limiter = RateLimiter(max_calls=1, window_seconds=60.0)
        limiter.check("key", now=0.0)
        with pytest.raises(RateLimitExceededError) as exc_info:
            limiter.check("key", now=10.0)
        assert 0.0 < exc_info.value.retry_after_seconds <= 60.0

    def test_window_resets_after_expiry(self):
        limiter = RateLimiter(max_calls=1, window_seconds=10.0)
        limiter.check("key", now=0.0)
        with pytest.raises(RateLimitExceededError):
            limiter.check("key", now=5.0)
        # Past the window: a fresh budget.
        limiter.check("key", now=11.0)  # must not raise

    def test_keys_are_independent(self):
        limiter = RateLimiter(max_calls=1, window_seconds=60.0)
        limiter.check("a", now=0.0)
        limiter.check("b", now=0.0)  # different key, must not raise
        with pytest.raises(RateLimitExceededError):
            limiter.check("a", now=0.0)

    def test_reset_one_key(self):
        limiter = RateLimiter(max_calls=1, window_seconds=60.0)
        limiter.check("a", now=0.0)
        limiter.reset("a")
        limiter.check("a", now=0.0)  # must not raise after reset

    def test_reset_all_keys(self):
        limiter = RateLimiter(max_calls=1, window_seconds=60.0)
        limiter.check("a", now=0.0)
        limiter.check("b", now=0.0)
        limiter.reset()
        limiter.check("a", now=0.0)
        limiter.check("b", now=0.0)  # neither raises after a full reset

    def test_uses_real_clock_when_now_not_supplied(self):
        limiter = RateLimiter(max_calls=1, window_seconds=60.0)
        limiter.check("key")  # must not raise; exercises the default clock

    def test_exception_message_mentions_retry(self):
        limiter = RateLimiter(max_calls=1, window_seconds=60.0)
        limiter.check("key", now=0.0)
        with pytest.raises(RateLimitExceededError, match="retry"):
            limiter.check("key", now=0.0)
