"""Tests for src.llm.reliability: CircuitBreaker and RetryPolicy/backoff.

Phase 23 (production reliability): these are pure, dependency-free unit tests
of the state machine and math, independent of any LLM provider. Integration
with RoutingProvider (retry-then-failover, breaker skipping a dead provider
across calls) is covered in test_factory.py.
"""

from __future__ import annotations

import pytest

from src.llm.reliability import CircuitBreaker, RetryPolicy, backoff_delay


class TestCircuitBreaker:
    def test_allows_calls_when_closed(self):
        breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=10.0)
        assert breaker.allow("p", now=0.0) is True
        assert breaker.is_open("p", now=0.0) is False

    def test_stays_closed_below_threshold(self):
        breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=10.0)
        breaker.record_failure("p", now=0.0)
        breaker.record_failure("p", now=0.0)
        assert breaker.allow("p", now=0.0) is True

    def test_opens_at_threshold(self):
        breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=10.0)
        for _ in range(3):
            breaker.record_failure("p", now=0.0)
        assert breaker.allow("p", now=0.0) is False
        assert breaker.is_open("p", now=0.0) is True

    def test_reopens_after_cooldown_elapses(self):
        breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=10.0)
        breaker.record_failure("p", now=0.0)
        assert breaker.allow("p", now=5.0) is False
        assert breaker.allow("p", now=10.0) is True  # cooldown exactly elapsed
        assert breaker.allow("p", now=15.0) is True

    def test_success_after_half_open_fully_closes(self):
        breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=1.0)
        breaker.record_failure("p", now=0.0)
        assert breaker.allow("p", now=1.0) is True  # half-open trial allowed
        breaker.record_success("p")
        # Fully closed: many failures below threshold don't reopen immediately.
        assert breaker.allow("p", now=1.0) is True

    def test_failure_during_half_open_reopens_and_restarts_cooldown(self):
        breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=1.0)
        breaker.record_failure("p", now=0.0)
        assert breaker.allow("p", now=1.0) is True  # half-open trial
        breaker.record_failure("p", now=1.0)  # trial failed
        assert breaker.allow("p", now=1.5) is False  # cooldown restarted from 1.0
        assert breaker.allow("p", now=2.0) is True

    def test_keys_are_independent(self):
        breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=100.0)
        breaker.record_failure("a", now=0.0)
        assert breaker.allow("a", now=0.0) is False
        assert breaker.allow("b", now=0.0) is True

    def test_reset_one_key(self):
        breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=100.0)
        breaker.record_failure("a", now=0.0)
        breaker.record_failure("b", now=0.0)
        breaker.reset("a")
        assert breaker.allow("a", now=0.0) is True
        assert breaker.allow("b", now=0.0) is False

    def test_reset_all_keys(self):
        breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=100.0)
        breaker.record_failure("a", now=0.0)
        breaker.record_failure("b", now=0.0)
        breaker.reset()
        assert breaker.allow("a", now=0.0) is True
        assert breaker.allow("b", now=0.0) is True

    def test_uses_real_clock_when_now_not_supplied(self):
        breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=60.0)
        breaker.record_failure("p")  # must not raise; exercises the default clock
        assert breaker.allow("p") is False


class TestBackoffDelay:
    def test_exponential_growth(self):
        assert backoff_delay(0, base_delay=1.0, max_delay=100.0) == 1.0
        assert backoff_delay(1, base_delay=1.0, max_delay=100.0) == 2.0
        assert backoff_delay(2, base_delay=1.0, max_delay=100.0) == 4.0

    def test_capped_at_max_delay(self):
        assert backoff_delay(10, base_delay=1.0, max_delay=5.0) == 5.0

    def test_retry_policy_delay_for_matches_backoff_delay(self):
        policy = RetryPolicy(max_retries=3, base_delay=0.5, max_delay=4.0)
        assert policy.delay_for(0) == 0.5
        assert policy.delay_for(1) == 1.0
        assert policy.delay_for(3) == 4.0  # capped

    def test_default_retry_policy_has_zero_retries(self):
        # Preserves pre-Phase-23 behavior for callers that don't opt in.
        assert RetryPolicy().max_retries == 0


@pytest.mark.parametrize("attempt", [0, 1, 2, 5])
def test_backoff_delay_never_negative(attempt):
    assert backoff_delay(attempt, base_delay=0.1, max_delay=1.0) >= 0.0
