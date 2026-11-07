"""Periodic maintenance: recovery and housekeeping (ADR-0035).

:func:`run_maintenance` is idempotent and safe to run at any time. It runs
in the API process every ``settings.maintenance_interval_seconds``, and on
demand with ``polyglot ops maintenance``. Each step is isolated: one
failing step is reported and the rest still run.

| Step | Why |
|---|---|
| recover idle chat sessions | abandoned sessions still reach the learner model (R1) |
| purge expired auth tokens | hygiene (R15) |
| purge expired retained audio | the 30-day consent window (ADR-0034) |
| prune idempotency keys (24 h) and LLM usage rows (90 days) | bounded tables |
| prune rate-limiter windows | bounded memory (R7) |
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.config import settings
from src.observability import metrics

logger = logging.getLogger("polyglot.ops.maintenance")


async def run_maintenance() -> dict[str, Any]:
    from src.api import auth, idempotency, sessions
    from src.api.deps import user_work_limiter
    from src.llm import governance
    from src.multimodal import store as media_store

    def limiter_prune() -> int:
        limiters = (auth.login_rate_limiter, auth.register_rate_limiter, user_work_limiter)
        return sum(limiter.prune() for limiter in limiters)

    report: dict[str, Any] = {}
    try:
        report["sessions"] = await sessions.recover_idle_sessions()
    except Exception as exc:  # noqa: BLE001 - report and continue
        report["sessions"] = {"error": type(exc).__name__}
    for name, step in (
        ("expired_tokens", auth.purge_expired_tokens),
        ("expired_media", media_store.purge_expired),
        ("idempotency_keys", idempotency.prune),
        ("llm_usage_rows", governance.prune_usage),
        ("rate_limit_windows", limiter_prune),
    ):
        try:
            report[name] = step()
        except Exception as exc:  # noqa: BLE001 - report and continue
            report[name] = {"error": type(exc).__name__}
    failed = any(isinstance(v, dict) and "error" in v for v in report.values())
    metrics.MAINTENANCE_RUNS.inc(outcome="partial" if failed else "ok")
    logger.info("maintenance run: %s", report)
    return report


async def maintenance_loop() -> None:
    """Run maintenance forever (cancelled at shutdown)."""
    interval = settings.maintenance_interval_seconds
    await asyncio.sleep(min(60.0, interval))  # let startup finish first
    while True:
        try:
            await run_maintenance()
        except Exception:  # noqa: BLE001 - the loop must survive anything
            logger.exception("maintenance run crashed")
            metrics.MAINTENANCE_RUNS.inc(outcome="crashed")
        await asyncio.sleep(interval)
