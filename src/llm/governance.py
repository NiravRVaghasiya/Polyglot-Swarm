"""LLM usage governance: budgets, quotas and loop guards (ADR-0035, R3).

Every LLM request through :class:`~src.llm.factory.RoutingProvider` calls
:func:`check_before_call` first and :func:`record_usage` after each attempt.

- **Per-turn call cap** (``llm_max_calls_per_turn``): a runaway agent loop
  inside one chat turn stops with :class:`BudgetExceededError`. It is bound
  by :func:`turn_scope` (``src.api.sessions.run_turn``).
- **Per-user daily budget** (``llm_user_daily_budget_usd``,
  ``llm_user_daily_calls``) for the principal the API bound
  (:func:`src.observability.context.current_principal`).
- **Deployment daily budget** (``llm_global_daily_budget_usd``) across all
  users and background work.

Usage is kept in ``llm_usage_daily`` (UTC days), so limits survive restarts.
Costs are the telemetry *estimates* (``src.llm.telemetry.estimate_cost``),
not provider invoices.

A budget stop is a policy decision, not a provider failure: it is never
retried and never triggers failover.

**Answering model.** :func:`note_answer` records which provider and model
actually answered each request in the current turn, and whether it was a
fallback, so the session's evidence can carry it (R12).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

from src.config import settings
from src.observability import metrics
from src.observability.context import current_principal

logger = logging.getLogger("polyglot.llm.governance")

GLOBAL_SCOPE = "*"


class BudgetExceededError(RuntimeError):
    """An LLM call was refused by a budget or quota."""

    def __init__(self, scope: str, message: str) -> None:
        super().__init__(message)
        self.scope = scope  # turn | user | global


_turn_calls: ContextVar[list[int] | None] = ContextVar("polyglot_turn_calls", default=None)
_turn_answers: ContextVar[list[str] | None] = ContextVar("polyglot_turn_answers", default=None)
#: ``provider:model`` of the latest answered call in this context.
_last_answer: ContextVar[str | None] = ContextVar("polyglot_last_answer", default=None)


@contextmanager
def turn_scope() -> Iterator[list[str]]:
    """Bind a fresh per-turn call counter; yields the answering-model list."""
    answers: list[str] = []
    calls_token = _turn_calls.set([0])
    answers_token = _turn_answers.set(answers)
    try:
        yield answers
    finally:
        _turn_calls.reset(calls_token)
        _turn_answers.reset(answers_token)


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def usage(scope: str, day: str | None = None) -> tuple[int, float]:
    """``(calls, cost_usd)`` recorded for ``scope`` on ``day`` (default today)."""
    import sqlite3

    from src.memory.db import get_connection

    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT calls, cost_usd FROM llm_usage_daily WHERE day = ? AND scope = ?",
                (day or _today(), scope),
            ).fetchone()
    except sqlite3.OperationalError:  # schema not migrated (bare test databases)
        return (0, 0.0)
    return (int(row["calls"]), float(row["cost_usd"])) if row else (0, 0.0)


def _refuse(scope: str, message: str) -> BudgetExceededError:
    metrics.LLM_BUDGET_REJECTIONS.inc(scope=scope)
    logger.warning("LLM call refused (%s budget): %s", scope, message)
    return BudgetExceededError(scope, message)


def check_before_call() -> None:
    """Raise :class:`BudgetExceededError` if this call would exceed a limit."""
    counter = _turn_calls.get()
    if counter is not None:
        if settings.llm_max_calls_per_turn > 0 and counter[0] >= settings.llm_max_calls_per_turn:
            raise _refuse("turn", "too many model calls in one turn")
        counter[0] += 1
    principal = current_principal()
    if principal:
        calls, cost = usage(principal)
        if settings.llm_user_daily_calls > 0 and calls >= settings.llm_user_daily_calls:
            raise _refuse("user", "daily model-call limit reached")
        if settings.llm_user_daily_budget_usd > 0 and cost >= settings.llm_user_daily_budget_usd:
            raise _refuse("user", "daily AI budget reached")
    if settings.llm_global_daily_budget_usd > 0:
        _, total = usage(GLOBAL_SCOPE)
        if total >= settings.llm_global_daily_budget_usd:
            raise _refuse("global", "deployment daily AI budget reached")


def record_usage(cost_usd: float) -> None:
    """Add one attempt and its estimated cost to today's counters (never raises)."""
    from src.memory.db import get_connection

    day = _today()
    scopes = [GLOBAL_SCOPE]
    principal = current_principal()
    if principal:
        scopes.append(principal)
    try:
        with get_connection() as conn:
            for scope in scopes:
                conn.execute(
                    "INSERT INTO llm_usage_daily (day, scope, calls, cost_usd) VALUES (?, ?, 1, ?) "
                    "ON CONFLICT(day, scope) DO UPDATE SET calls = calls + 1, "
                    "cost_usd = cost_usd + excluded.cost_usd",
                    (day, scope, max(0.0, cost_usd)),
                )
    except Exception as exc:  # noqa: BLE001 - accounting must not break a learner's turn
        logger.error("could not record LLM usage: %s", exc)


def note_answer(provider: str, model: str | None, *, fallback: bool) -> None:
    """Remember which model answered a request in the current turn."""
    _last_answer.set(f"{provider}:{model or 'unknown'}")
    answers = _turn_answers.get()
    if answers is None:
        return
    label = f"{provider}:{model or 'unknown'}" + (" (fallback)" if fallback else "")
    if label not in answers:
        answers.append(label)


def last_answer() -> str | None:
    """``provider:model`` of the most recent answered call in this context.

    Read right after awaiting a call to learn which model produced it (for
    per-model calibration). Concurrent graph nodes run in separate tasks, so
    they do not see each other's answers.
    """
    return _last_answer.get()


def prune_usage(keep_days: int = 90) -> int:
    """Delete usage rows older than ``keep_days`` (maintenance)."""
    from datetime import timedelta

    from src.memory.db import get_connection

    cutoff = (datetime.now(UTC) - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    with get_connection() as conn:
        return conn.execute("DELETE FROM llm_usage_daily WHERE day < ?", (cutoff,)).rowcount
