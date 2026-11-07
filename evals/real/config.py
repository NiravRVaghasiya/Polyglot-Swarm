"""Versioned evaluation configuration.

Everything that changes what a run measures lives here and is hashed into
the run id, so two runs with equal ``config_hash`` and dataset checksums
asked the models exactly the same questions in exactly the same way.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, Field

CONFIGS_DIR = Path(__file__).parent / "configs"


#: Settings that affect only how calls are executed, not what is measured.
EXECUTION_FIELDS = ("timeout_s", "max_retries", "retry_backoff_s", "concurrency")


class QualityGate(BaseModel):
    """A threshold on one metric, judged against its confidence interval.

    ``direction`` says which side is good. A gate *passes* only when the whole
    interval is on the good side, *fails* only when the whole interval is on
    the bad side, and is *inconclusive* otherwise — a point estimate alone
    never passes or fails a gate.
    """

    metric: str
    threshold: float
    direction: str = Field(pattern="^(max|min)$")  # max: value <= threshold is good


class EvalConfig(BaseModel):
    config_version: str = "real-eval-config-1.0"
    tasks: list[str] = Field(default_factory=lambda: ["grammar", "vocabulary"])
    split: str = "test"
    #: Grammar prompt variants as ``name@version``. ``grammar@1`` is production.
    grammar_prompts: list[str] = Field(default_factory=lambda: ["grammar@1"])
    #: Run non-production grammar variants only on cases that carry a context.
    variants_only_with_context: bool = True
    #: None -> use the production agents' parameters (temperature 0, 700/500 tokens).
    temperature: float | None = None
    max_tokens_grammar: int | None = None
    max_tokens_vocabulary: int | None = None
    timeout_s: float = 180.0
    max_retries: int = 2
    retry_backoff_s: float = 2.0
    concurrency: int = 1
    #: Repeat each call this many times to measure run-to-run consistency.
    repeats: int = 1
    #: Fixed seed for bootstrap resampling in reports.
    bootstrap_seed: int = 20261106
    bootstrap_samples: int = 2000
    #: Regression: significance level of the paired test.
    regression_alpha: float = 0.05
    gates: list[QualityGate] = Field(
        default_factory=lambda: [
            QualityGate(metric="grammar.false_correction_rate", threshold=0.10, direction="max"),
            QualityGate(metric="grammar.recall", threshold=0.60, direction="min"),
            QualityGate(metric="structured.schema_valid_rate", threshold=0.95, direction="min"),
        ]
    )

    def config_hash(self) -> str:
        """Hash of everything that changes *what is measured*.

        Execution-only settings (timeouts, retries, concurrency) are excluded:
        they decide whether a call completes, not what it asks, so a resumed
        run with a longer timeout is still the same measurement.
        """
        data = self.model_dump(mode="json", exclude=set(EXECUTION_FIELDS))
        blob = json.dumps(data, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()[:12]

    @classmethod
    def load(cls, name_or_path: str = "default") -> EvalConfig:
        path = Path(name_or_path)
        if not path.suffix:
            path = CONFIGS_DIR / f"{name_or_path}.json"
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


def parse_prompt_ref(ref: str) -> tuple[str, int]:
    name, _, version = ref.partition("@")
    return name, int(version or 1)
