"""Shared helpers in :mod:`src.util`."""

from __future__ import annotations

import math
from datetime import datetime

from src.util import logit, parse_timestamp, sigmoid, utc_now_iso


def test_utc_now_iso_is_timezone_aware_iso():
    parsed = datetime.fromisoformat(utc_now_iso())
    assert parsed.utcoffset() is not None
    assert parsed.utcoffset().total_seconds() == 0


def test_parse_timestamp():
    assert parse_timestamp("1970-01-01T00:00:10+00:00") == 10.0
    assert parse_timestamp(None) is None
    assert parse_timestamp("") is None
    assert parse_timestamp("not a date") is None


def test_sigmoid_is_stable_and_inverts_logit():
    assert sigmoid(0.0) == 0.5
    assert sigmoid(1000.0) == 1.0
    assert sigmoid(-1000.0) == 0.0  # no OverflowError
    for p in (0.01, 0.3, 0.5, 0.9):
        assert math.isclose(sigmoid(logit(p)), p, rel_tol=1e-9)


def test_logit_clamps_the_boundaries():
    assert math.isfinite(logit(0.0))
    assert math.isfinite(logit(1.0))
