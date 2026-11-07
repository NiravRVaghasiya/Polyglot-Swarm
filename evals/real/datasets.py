"""Build, load and validate the versioned real-model evaluation datasets.

Each task's cases are authored in ``datasets/<task>/source.yaml``.
:func:`build_dataset` turns them into a published, versioned split
(``datasets/<task>/<version>/{dev,test}.jsonl`` plus ``manifest.json``):

- **Splits are by group.** A case's split is a pure function of its
  ``group_id`` (SHA-256 of a fixed salt plus the group id; about 30% of groups
  go to ``dev``), so variants of one item never straddle splits, and adding a
  case never moves existing ones.
- **Files are checksummed.** The manifest stores the SHA-256 of every
  published file; :func:`load_split` refuses a file whose bytes do not match,
  so a reported result always refers to exactly one dataset state.
- **No synthetic or author labels pass as expert.** Validation status is per
  case and summarized in the manifest; reports read it.

``dev`` is for prompt development and for fitting calibration maps; ``test``
is held out and is what benchmark numbers are reported on.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel

from evals.real.schema import (
    SCHEMA_VERSION,
    Annotation,
    DatasetManifest,
    ExpectedError,
    ExpectedWord,
    GrammarCase,
    VocabularyCase,
)

DATASETS_DIR = Path(__file__).parent / "datasets"
_SPLIT_SALT = "polyglot-real-eval-split-v1"
#: Share of groups assigned to the dev split (by hash bucket).
DEV_FRACTION = 0.3
TASKS = ("grammar", "vocabulary")

_CaseT = TypeVar("_CaseT", bound=BaseModel)


class DatasetIntegrityError(RuntimeError):
    """A published dataset file does not match its manifest."""


def split_for_group(group_id: str) -> str:
    """The split a group belongs to: deterministic, independent of other cases."""
    digest = hashlib.sha256(f"{_SPLIT_SALT}:{group_id}".encode()).hexdigest()
    bucket = int(digest[:8], 16) / 0xFFFFFFFF
    return "dev" if bucket < DEV_FRACTION else "test"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _annotation(source: dict[str, Any], has_error: bool | None, rubric: str) -> Annotation:
    ann = source["annotator"]
    return Annotation(
        annotator_id=str(ann["id"]),
        annotator_type=ann["type"],
        has_error=has_error,
        rubric_version=rubric,
        annotated_at=str(ann["date"]),
    )


def _status(source: dict[str, Any]) -> str:
    ann_type = source["annotator"]["type"]
    return "expert_validated" if ann_type in ("expert", "trained_annotator") else "author_labeled"


def _grammar_case(raw: dict[str, Any], source: dict[str, Any]) -> GrammarCase:
    rubric = str(source["rubric_version"])
    errors = [
        ExpectedError(
            span=e["span"],
            corrections=list(e["fix"]),
            constructions=list(e["cons"]),
            skill=e.get("skill", "grammar"),
            construction_cefr=e.get("ccefr"),
        )
        for e in raw.get("errors", [])
    ]
    case = GrammarCase(
        case_id=raw["id"],
        group_id=raw["group"],
        language=raw["lang"],
        text=raw["text"],
        context=raw.get("context"),
        category=raw["cat"],
        cefr_level=raw["cefr"],
        difficulty=raw["diff"],
        has_error=raw["err"],
        expected_errors=errors,
        acceptable_classifications=list(raw.get("ok_as", [])),
        acceptable_variants=list(raw.get("variants", [])),
        tags=list(raw.get("tags", [])),
        annotations=[_annotation(source, raw["err"], rubric)],
        validation_status=_status(source),  # type: ignore[arg-type]
        rationale=raw.get("why", ""),
    )
    return case.model_copy(update={"split": split_for_group(case.group_id)})


def _vocabulary_case(raw: dict[str, Any], source: dict[str, Any]) -> VocabularyCase:
    rubric = str(source["rubric_version"])
    case = VocabularyCase(
        case_id=raw["id"],
        group_id=raw["group"],
        language=raw["lang"],
        cefr_level=raw["cefr"],
        difficulty=raw["diff"],
        user_text=raw["user"],
        agent_text=raw["agent"],
        required_words=[
            ExpectedWord(
                word=w["word"],
                forms=list(w.get("forms", [])),
                translations=list(w["tr"]),
                produced_by_learner=bool(w.get("produced", False)),
            )
            for w in raw.get("req", [])
        ],
        optional_words=list(raw.get("opt", [])),
        forbidden_words=list(raw.get("forbid", [])),
        tags=list(raw.get("tags", [])),
        annotations=[_annotation(source, None, rubric)],
        validation_status=_status(source),  # type: ignore[arg-type]
    )
    return case.model_copy(update={"split": split_for_group(case.group_id)})


def load_source(task: str) -> tuple[dict[str, Any], list[GrammarCase | VocabularyCase]]:
    """Parse and validate a task's ``source.yaml``; returns (header, cases)."""
    path = DATASETS_DIR / task / "source.yaml"
    source = yaml.safe_load(path.read_text(encoding="utf-8"))
    build: Any = _grammar_case if task == "grammar" else _vocabulary_case
    cases: list[GrammarCase | VocabularyCase] = [build(raw, source) for raw in source["cases"]]
    ids = [c.case_id for c in cases]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise ValueError(f"duplicate case ids in {task}: {dupes}")
    return source, cases


def _jsonl(cases: list[GrammarCase | VocabularyCase]) -> bytes:
    lines = [
        json.dumps(c.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) for c in cases
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def render_dataset(task: str) -> tuple[DatasetManifest, dict[str, bytes]]:
    """Compute the published files for a task without writing them."""
    source, cases = load_source(task)
    files: dict[str, bytes] = {}
    for split in ("dev", "test"):
        files[f"{split}.jsonl"] = _jsonl([c for c in cases if c.split == split])
    counts: dict[str, int] = {"total": len(cases)}
    for split in ("dev", "test"):
        counts[split] = sum(1 for c in cases if c.split == split)
    statuses: dict[str, int] = {}
    for c in cases:
        status = c.validation_status
        statuses[status] = statuses.get(status, 0) + 1
    manifest = DatasetManifest(
        dataset=str(source["dataset"]),
        version=str(source["version"]),
        schema_version=SCHEMA_VERSION,
        rubric_version=str(source["rubric_version"]),
        task=task,  # type: ignore[arg-type]
        created=str(source["annotator"]["date"]),
        languages=sorted({c.language for c in cases}),
        counts=counts,
        validation_status_counts=statuses,
        files={name: _sha256(data) for name, data in files.items()},
        split_rule=(
            f"sha256('{_SPLIT_SALT}:' + group_id); first 32 bits / 2^32 < {DEV_FRACTION} -> dev"
        ),
        provenance=(
            f"Cases written and labeled by {source['annotator']['id']} "
            f"({source['annotator']['type']}) under {source['rubric_version']}. "
            "No qualified human expert has reviewed them."
        ),
        known_limitations=[
            "Single annotator: no inter-annotator agreement can be computed.",
            "Labels are author judgments, not expert-validated; quality gates "
            "built on this dataset are provisional.",
            "The annotator is itself an LLM, which may share blind spots with the "
            "models under evaluation.",
        ],
    )
    return manifest, files


def build_dataset(task: str) -> Path:
    """Write a task's published split files + manifest. Returns the version dir."""
    manifest, files = render_dataset(task)
    out = DATASETS_DIR / task / manifest.version
    out.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (out / name).write_bytes(data)
    (out / "manifest.json").write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return out


def latest_version(task: str) -> str:
    """The newest published version directory of a task."""
    versions = sorted(p.name for p in (DATASETS_DIR / task).iterdir() if p.is_dir())
    if not versions:
        raise FileNotFoundError(f"no published dataset for {task}")
    return versions[-1]


def load_manifest(task: str, version: str | None = None) -> DatasetManifest:
    version = version or latest_version(task)
    path = DATASETS_DIR / task / version / "manifest.json"
    return DatasetManifest.model_validate_json(path.read_text(encoding="utf-8"))


def load_split(
    task: str, split: str, version: str | None = None
) -> tuple[DatasetManifest, list[GrammarCase] | list[VocabularyCase]]:
    """Load one split, verifying its checksum against the manifest."""
    manifest = load_manifest(task, version)
    path = DATASETS_DIR / task / manifest.version / f"{split}.jsonl"
    data = path.read_bytes()
    expected = manifest.files.get(f"{split}.jsonl")
    if expected != _sha256(data):
        raise DatasetIntegrityError(
            f"{path} does not match its manifest checksum; rebuild with "
            "`python -m evals.real build-datasets` (and bump the version if labels changed)"
        )
    model: type[GrammarCase] | type[VocabularyCase] = (
        GrammarCase if task == "grammar" else VocabularyCase
    )
    cases = [model.model_validate_json(line) for line in data.decode("utf-8").splitlines() if line]
    return manifest, cases  # type: ignore[return-value]


def _normalize_text(text: str) -> str:
    return " ".join(text.lower().split())


def leakage_report(task: str, version: str | None = None) -> dict[str, list[str]]:
    """Check the published splits for leakage. Empty lists mean no leakage.

    - ``shared_groups``: a group id in both splits;
    - ``shared_texts``: the same normalized text in both splits;
    - ``in_prompts``: a test text that appears verbatim in a prompt template
      (which would leak test items into every model call).
    """
    _, dev = load_split(task, "dev", version)
    _, test = load_split(task, "test", version)

    def texts(cases: list[Any]) -> set[str]:
        out = set()
        for c in cases:
            for t in (getattr(c, "text", None), getattr(c, "user_text", None)):
                if t:
                    out.add(_normalize_text(t))
        return out

    dev_groups = {c.group_id for c in dev}
    test_groups = {c.group_id for c in test}
    prompt_dir = Path(__file__).resolve().parents[2] / "src" / "llm" / "prompts"
    prompts = " ".join(
        _normalize_text(p.read_text(encoding="utf-8")) for p in prompt_dir.glob("*.jinja2")
    )
    return {
        "shared_groups": sorted(dev_groups & test_groups),
        "shared_texts": sorted(texts(dev) & texts(test)),
        "in_prompts": sorted(t for t in texts(test) if t in prompts),
    }


def manifest_age() -> str:
    """Timestamp helper for reports (UTC ISO-8601)."""
    return datetime.now(UTC).isoformat()
