"""Per-model calibration maps for grammar-correction confidence.

A model's self-reported confidence is not a probability that its correction
is right. A calibration map turns it into one, fitted per provider/model on
the real-model evaluation's **dev** split (``python -m evals.real calibrate``)
and stored, versioned, as one JSON file per model under
``evals/real/calibration/``.

:func:`src.agents.grammar._select_errors` applies the map of the model that
answered (:func:`load_map`); a correction is surfaced when its *calibrated*
probability reaches the same 0.5 threshold. Without a usable map it keeps the
raw-confidence threshold and logs that the result is uncalibrated.

A map file has ``status`` ``fitted`` or ``insufficient_dev_data`` (too few
dev predictions, or one class only, to fit anything); only ``fitted`` maps
are applied. A file that cannot be read or validated is logged and ignored.

The method (Platt scaling or histogram binning, both from
:mod:`src.evaluation.statistics`) is chosen on the dev data alone, by
leave-one-out Brier score, so the test split never influences a map.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.evaluation.statistics import brier_score, fit_histogram_binning, fit_platt

logger = logging.getLogger("polyglot.calibration")

#: Format of a map file; bump on incompatible changes.
CALIBRATION_VERSION = "grammar-calibration-1.0"
#: Where the committed maps live (relative to the repository root).
DEFAULT_DIR = Path(__file__).resolve().parents[2] / "evals" / "real" / "calibration"
#: Fewer dev predictions than this (or one class only) are not fitted.
MIN_DEV_PREDICTIONS = 15
HISTOGRAM_BINS = 5
FITTED = "fitted"
INSUFFICIENT = "insufficient_dev_data"

Pair = tuple[float, bool]


@dataclass(frozen=True)
class CalibrationMap:
    """A fitted map from raw confidence to P(correction is right)."""

    key: str
    method: str  # "platt" | "histogram"
    params: dict[str, Any]
    n: int
    source: dict[str, Any]

    def __call__(self, confidence: float) -> float:
        return _predictor(self.method, self.params)(confidence)


def _predictor(method: str, params: dict[str, Any]) -> Callable[[float], float]:
    from src.evaluation.statistics import HistogramMap, PlattMap

    if method == "platt":
        return PlattMap(float(params["a"]), float(params["b"]), 0)
    if method == "histogram":
        edges = tuple(float(x) for x in params["edges"])
        values = tuple(float(x) for x in params["values"])
        if len(edges) != len(values) + 1 or not values:
            raise ValueError("histogram map needs len(edges) == len(values) + 1")
        return HistogramMap(edges, values, 0)
    raise ValueError(f"unknown calibration method {method!r}")


def map_filename(key: str) -> str:
    """A portable file name for a ``provider:model`` key."""
    return re.sub(r"[^A-Za-z0-9.-]+", "_", key).strip("_") + ".json"


# --- fitting (dev data only) ---------------------------------------------------


def _fit(method: str, pairs: Sequence[Pair]) -> dict[str, Any]:
    if method == "platt":
        platt = fit_platt(pairs)
        return {"a": round(platt.a, 6), "b": round(platt.b, 6)}
    hist = fit_histogram_binning(pairs, bins=HISTOGRAM_BINS)
    return {"edges": list(hist.edges), "values": [round(v, 6) for v in hist.values]}


def _loo_brier(method: str, pairs: Sequence[Pair]) -> float:
    """Leave-one-out Brier score of ``method`` on ``pairs``."""
    predictions = []
    for i, (confidence, outcome) in enumerate(pairs):
        rest = [p for j, p in enumerate(pairs) if j != i]
        predictions.append((_predictor(method, _fit(method, rest))(confidence), outcome))
    return brier_score(predictions)


def fit_map(key: str, dev_pairs: Sequence[Pair], source: dict[str, Any]) -> dict[str, Any]:
    """Fit a map document for one model from its dev ``(confidence, correct)`` pairs.

    ``source`` must describe a dev-split run (``source["split"] == "dev"``).
    Returns the JSON document to store; ``status`` is ``insufficient_dev_data``
    when there is too little dev data to fit.
    """
    if source.get("split") != "dev":
        raise ValueError(
            f"calibration maps are fitted on the dev split only, not {source.get('split')!r}"
        )
    doc: dict[str, Any] = {
        "calibration_version": CALIBRATION_VERSION,
        "key": key,
        "target": "P(surfaced grammar correction matches an expected error)",
        "source": source,
        "dev_predictions": len(dev_pairs),
        "dev_positive": sum(1 for _, y in dev_pairs if y),
    }
    if len(dev_pairs) < MIN_DEV_PREDICTIONS or len({y for _, y in dev_pairs}) < 2:
        return {**doc, "status": INSUFFICIENT, "required": MIN_DEV_PREDICTIONS}
    scores = {m: round(_loo_brier(m, dev_pairs), 6) for m in ("platt", "histogram")}
    method = min(scores, key=lambda m: (scores[m], m != "platt"))
    return {
        **doc,
        "status": FITTED,
        "method": method,
        "params": _fit(method, dev_pairs),
        "selection": {"criterion": "leave-one-out Brier on dev", "scores": scores},
    }


# --- loading -----------------------------------------------------------------------

_cache: dict[tuple[str, str], CalibrationMap | None] = {}


def _parse(doc: Any, key: str) -> CalibrationMap | None:
    if not isinstance(doc, dict) or doc.get("calibration_version") != CALIBRATION_VERSION:
        raise ValueError("not a grammar calibration map of version " + CALIBRATION_VERSION)
    if doc.get("key") != key:
        raise ValueError(f"map is for {doc.get('key')!r}, not {key!r}")
    if doc.get("status") != FITTED:
        return None
    source = doc.get("source")
    if not isinstance(source, dict) or source.get("split") != "dev":
        raise ValueError("map was not fitted on the dev split")
    cal = CalibrationMap(
        key=key,
        method=str(doc["method"]),
        params=dict(doc["params"]),
        n=int(doc["dev_predictions"]),
        source=source,
    )
    probe = cal(0.5)  # validates the parameters
    if not 0.0 <= probe <= 1.0:
        raise ValueError("map produces values outside [0, 1]")
    return cal


def load_map(key: str, directory: Path | None = None) -> CalibrationMap | None:
    """The fitted map for ``provider:model``, or ``None`` if there is none.

    ``None`` covers no file, a file with ``insufficient_dev_data``, and a
    corrupt or invalid file (logged as an error). Results are cached per
    process.
    """
    folder = directory or DEFAULT_DIR
    cache_key = (str(folder), key)
    if cache_key in _cache:
        return _cache[cache_key]
    path = folder / map_filename(key)
    cal: CalibrationMap | None = None
    if path.exists():
        try:
            cal = _parse(json.loads(path.read_text(encoding="utf-8")), key)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.error("ignoring calibration map %s: %s", path, exc)
            cal = None
    _cache[cache_key] = cal
    return cal


def clear_cache() -> None:
    """Forget loaded maps (tests, or after refitting)."""
    _cache.clear()
