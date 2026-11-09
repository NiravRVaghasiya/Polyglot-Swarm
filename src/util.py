"""Small shared helpers used across the package.

Kept dependency-free so any module (storage, API, models) can import them
without import cycles.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any


def utc_now_iso() -> str:
    """The current UTC time as an ISO-8601 string (the format stored in SQLite)."""
    return datetime.now(UTC).isoformat()


def parse_timestamp(value: Any) -> float | None:
    """An ISO-8601 value as a POSIX timestamp; ``None`` if empty or unparseable."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except ValueError:
        return None


def sigmoid(x: float) -> float:
    """The logistic function, numerically stable for large ``|x|``."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def logit(p: float) -> float:
    """The inverse of :func:`sigmoid`, with ``p`` clamped away from 0 and 1."""
    p = min(1.0 - 1e-9, max(1e-9, p))
    return math.log(p / (1.0 - p))
