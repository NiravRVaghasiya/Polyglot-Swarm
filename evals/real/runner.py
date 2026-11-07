"""Run benchmark cases against real providers and preserve every raw response.

A run is a directory ``evals/real/runs/<run_id>/``:

- ``manifest.json`` — what was run (config and its hash, dataset versions and
  checksums, prompt versions and template hashes, git commit, environment,
  each provider's probe outcome) and how it ended (``complete`` /
  ``partial`` / ``failed`` / ``running``).
- ``responses.jsonl`` — one record per model call: the exact messages sent,
  generation parameters, the raw text returned, reported model, token usage
  (flagged when estimated), estimated cost, latency, attempts, and any error.

Scoring never calls a model: :mod:`evals.real.scoring` reads
``responses.jsonl``, so a run can be rescored when a metric changes without
paying for it again. Runs are resumable: records already present are skipped.

Guarantees:

- providers are built individually (:mod:`evals.real.providers`), never
  through the failover router, so a result is always from the model it names;
- a provider whose probe fails is recorded as unavailable and not run — it is
  never replaced by another provider or by synthetic output;
- the deterministic fake provider runs only with ``allow_synthetic=True`` and
  marks the whole run ``synthetic``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.real import providers as prov
from evals.real.config import EvalConfig, parse_prompt_ref
from evals.real.datasets import load_split
from evals.real.schema import GrammarCase, VocabularyCase
from src.llm.provider import LLMProvider, Message
from src.llm.telemetry import estimate_cost

RUNS_DIR = Path(__file__).parent / "runs"
_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "src" / "llm" / "prompts"


@dataclass(frozen=True)
class CallPlan:
    """One model call to make."""

    task: str
    case_id: str
    prompt: str  # name@version
    repeat: int
    messages: list[Message]
    temperature: float
    max_tokens: int

    def key(self, provider_key: str) -> str:
        return f"{provider_key}|{self.task}|{self.case_id}|{self.prompt}|{self.repeat}"


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=Path(__file__).resolve().parents[2],
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _package_versions() -> dict[str, str]:
    from importlib import metadata

    out = {}
    for pkg in (
        "langchain-core",
        "langchain-anthropic",
        "langchain-openai",
        "langchain-google-genai",
        "langchain-ollama",
        "pydantic",
    ):
        try:
            out[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            out[pkg] = "not installed"
    return out


def prompt_fingerprints(refs: list[str]) -> dict[str, dict[str, str]]:
    """Template file and SHA-256 for each ``name@version`` prompt reference."""
    from src.llm.prompts.registry import _versioned_template_name

    out = {}
    for ref in refs:
        name, version = parse_prompt_ref(ref)
        template = _versioned_template_name(name, version)
        data = (_PROMPTS_DIR / template).read_bytes()
        out[ref] = {"template": template, "sha256": hashlib.sha256(data).hexdigest()}
    return out


def plan_calls(config: EvalConfig) -> tuple[list[CallPlan], dict[str, Any]]:
    """Every call a run will make, plus the dataset identities they come from."""
    from src.agents.grammar import (
        GRAMMAR_MAX_TOKENS,
        GRAMMAR_TEMPERATURE,
        build_grammar_messages,
    )
    from src.agents.vocabulary import (
        VOCABULARY_MAX_TOKENS,
        VOCABULARY_TEMPERATURE,
        build_vocabulary_messages,
    )

    calls: list[CallPlan] = []
    datasets: dict[str, Any] = {}
    if "grammar" in config.tasks:
        manifest, cases = load_split("grammar", config.split)
        datasets["grammar"] = {
            "version": manifest.version,
            "split": config.split,
            "sha256": manifest.files[f"{config.split}.jsonl"],
            "cases": len(cases),
            "validation_status_counts": manifest.validation_status_counts,
        }
        for ref in config.grammar_prompts:
            name, version = parse_prompt_ref(ref)
            for case in cases:
                assert isinstance(case, GrammarCase)
                if name != "grammar" and config.variants_only_with_context and not case.context:
                    continue
                extra = {"context": case.context} if name != "grammar" else {}
                messages = build_grammar_messages(
                    case.language,
                    cefr_level=case.cefr_level,
                    weaknesses=[],
                    user_text=case.text,
                    prompt_name=name,
                    prompt_version=version,
                    **extra,
                )
                for r in range(config.repeats):
                    calls.append(
                        CallPlan(
                            "grammar",
                            case.case_id,
                            ref,
                            r,
                            messages,
                            GRAMMAR_TEMPERATURE
                            if config.temperature is None
                            else config.temperature,
                            config.max_tokens_grammar or GRAMMAR_MAX_TOKENS,
                        )
                    )
    if "vocabulary" in config.tasks:
        manifest, vcases = load_split("vocabulary", config.split)
        datasets["vocabulary"] = {
            "version": manifest.version,
            "split": config.split,
            "sha256": manifest.files[f"{config.split}.jsonl"],
            "cases": len(vcases),
            "validation_status_counts": manifest.validation_status_counts,
        }
        for case in vcases:
            assert isinstance(case, VocabularyCase)
            messages = build_vocabulary_messages(
                case.language,
                cefr_level=case.cefr_level,
                user_text=case.user_text,
                agent_text=case.agent_text,
            )
            for r in range(config.repeats):
                calls.append(
                    CallPlan(
                        "vocabulary",
                        case.case_id,
                        "vocabulary@1",
                        r,
                        messages,
                        VOCABULARY_TEMPERATURE
                        if config.temperature is None
                        else config.temperature,
                        config.max_tokens_vocabulary or VOCABULARY_MAX_TOKENS,
                    )
                )
    return calls, datasets


async def execute_call(
    provider: LLMProvider,
    spec: prov.ProviderSpec,
    call: CallPlan,
    config: EvalConfig,
    *,
    sleep: Callable[[float], Any] = asyncio.sleep,
) -> dict[str, Any]:
    """Make one call with timeout + retries and return its full record."""
    attempts = 0
    errors: list[str] = []
    started = datetime.now(UTC).isoformat()
    while True:
        attempts += 1
        t0 = time.perf_counter()
        try:
            completion = await asyncio.wait_for(
                provider.generate_detailed(
                    call.messages,
                    temperature=call.temperature,
                    max_tokens=call.max_tokens,
                    json_mode=True,
                ),
                timeout=config.timeout_s,
            )
        except Exception as exc:  # noqa: BLE001 - every failure is recorded
            category = prov.classify_error(exc)
            errors.append(f"{category}: {type(exc).__name__}: {str(exc)[:300]}")
            retryable = category in (prov.TIMEOUT, prov.UNREACHABLE, prov.ERROR)
            if retryable and attempts <= config.max_retries:
                await sleep(config.retry_backoff_s * attempts)
                continue
            return _record(spec, call, started, attempts, (time.perf_counter() - t0) * 1000) | {
                "ok": False,
                "error_category": category,
                "errors": errors,
                "response_text": None,
            }
        latency = (time.perf_counter() - t0) * 1000
        cost = estimate_cost(spec.model, completion.input_tokens, completion.output_tokens)
        return _record(spec, call, started, attempts, latency) | {
            "ok": True,
            "error_category": None,
            "errors": errors,
            "response_text": completion.text,
            "reported_model": completion.reported_model,
            "response_metadata": completion.metadata,
            "input_tokens": completion.input_tokens,
            "output_tokens": completion.output_tokens,
            "tokens_estimated": completion.tokens_estimated,
            "cost_usd": cost,
            "cost_estimated": True,
        }


def _record(
    spec: prov.ProviderSpec, call: CallPlan, started: str, attempts: int, latency_ms: float
) -> dict[str, Any]:
    return {
        "key": call.key(spec.key),
        "provider": spec.provider,
        "model": spec.model,
        "synthetic": spec.synthetic,
        "task": call.task,
        "case_id": call.case_id,
        "prompt": call.prompt,
        "repeat": call.repeat,
        "temperature": call.temperature,
        "max_tokens": call.max_tokens,
        "messages": [{"role": m.role, "content": m.content} for m in call.messages],
        "started_at": started,
        "attempts": attempts,
        "latency_ms": round(latency_ms, 1),
    }


def _read_done(path: Path) -> set[str]:
    if not path.exists():
        return set()
    done = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            if rec.get("ok"):
                done.add(rec["key"])
    return done


def new_run_id(config: EvalConfig) -> str:
    return f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{config.config_hash()[:6]}"


def _write_manifest(run_dir: Path, manifest: dict[str, Any]) -> None:
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


async def run(
    config: EvalConfig,
    specs: list[prov.ProviderSpec],
    *,
    run_id: str | None = None,
    runs_dir: Path = RUNS_DIR,
    allow_synthetic: bool = False,
    limit: int | None = None,
    probe_timeout_s: float = 120.0,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Execute (or resume) a run and return its directory."""
    calls, datasets = plan_calls(config)
    if limit is not None:
        calls = calls[:limit]
    run_id = run_id or new_run_id(config)
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    responses = run_dir / "responses.jsonl"
    done = _read_done(responses)
    say = progress or (lambda _msg: None)

    previous: dict[str, Any] | None = None
    if (run_dir / "manifest.json").exists():
        previous = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        if previous["config_hash"] != config.config_hash():
            raise ValueError(
                f"run {run_id} was made with config {previous['config_hash']}, not "
                f"{config.config_hash()}; start a new run instead of mixing measurements"
            )

    probes = [
        await prov.probe(s, timeout_s=probe_timeout_s, allow_synthetic=allow_synthetic)
        for s in specs
    ]
    # A resumed run keeps the probe records of providers it is not re-running.
    probe_dicts = [p.as_dict() for p in probes]
    if previous is not None:
        current = {f"{p['provider']}:{p['model']}" for p in probe_dicts}
        probe_dicts = [
            p for p in previous["providers"] if f"{p['provider']}:{p['model']}" not in current
        ] + probe_dicts
    synthetic = any(s.synthetic for s in specs) or bool(previous and previous.get("synthetic"))
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "created_at": previous["created_at"] if previous else datetime.now(UTC).isoformat(),
        "resumed_at": datetime.now(UTC).isoformat() if previous else None,
        "status": "running",
        "synthetic": synthetic,
        "config": config.model_dump(mode="json"),
        "config_hash": config.config_hash(),
        "datasets": datasets,
        "prompts": prompt_fingerprints(
            [*config.grammar_prompts, *(["vocabulary@1"] if "vocabulary" in config.tasks else [])]
        ),
        "providers": probe_dicts,
        "execution": {
            "timeout_s": config.timeout_s,
            "max_retries": config.max_retries,
            "concurrency": config.concurrency,
        },
        "planned_calls_per_provider": len(calls),
        "limit": limit,
        "git": {"commit": _git("rev-parse", "HEAD"), "dirty": bool(_git("status", "--porcelain"))},
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "deterministic_env": os.getenv("POLYGLOT_DETERMINISTIC", ""),
            "packages": _package_versions(),
        },
    }
    _write_manifest(run_dir, manifest)

    semaphore = asyncio.Semaphore(max(1, config.concurrency))
    with responses.open("a", encoding="utf-8") as fh:
        for probe_result in probes:
            if probe_result.status != prov.AVAILABLE:
                say(f"skip {probe_result.spec.key}: {probe_result.status}")
                continue
            spec = probe_result.spec
            provider = prov.build_provider(spec, allow_synthetic=allow_synthetic)
            todo = [c for c in calls if c.key(spec.key) not in done]
            say(f"{spec.key}: {len(todo)} of {len(calls)} calls to make")

            async def one(
                call: CallPlan, provider: LLMProvider = provider, spec: prov.ProviderSpec = spec
            ) -> dict[str, Any]:
                async with semaphore:
                    return await execute_call(provider, spec, call, config)

            for i, coro in enumerate(asyncio.as_completed([one(c) for c in todo]), 1):
                record = await coro
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                fh.flush()
                status = "ok" if record["ok"] else record["error_category"]
                say(
                    f"  [{i}/{len(todo)}] {record['task']} {record['case_id']} "
                    f"{status} {record['latency_ms']:.0f}ms"
                )

    manifest["status"] = completion_status(run_dir, manifest)
    manifest["finished_at"] = datetime.now(UTC).isoformat()
    _write_manifest(run_dir, manifest)
    return run_dir


def load_responses(run_dir: Path) -> list[dict[str, Any]]:
    """Latest record per call key (a resumed run may contain earlier failures)."""
    latest: dict[str, dict[str, Any]] = {}
    path = run_dir / "responses.jsonl"
    if not path.exists():
        return []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            prior = latest.get(rec["key"])
            if prior is None or rec.get("ok") or not prior.get("ok"):
                latest[rec["key"]] = rec
    return list(latest.values())


def completion_status(run_dir: Path, manifest: dict[str, Any]) -> str:
    """``complete``: every planned call of every requested provider succeeded.
    ``partial``: some calls or providers missing/failed but some results exist.
    ``failed``: no successful call at all."""
    records = load_responses(run_dir)
    ok = [r for r in records if r.get("ok")]
    if not ok:
        return "failed"
    planned = int(manifest["planned_calls_per_provider"])
    requested = len(manifest["providers"])
    if len(ok) == planned * requested:
        return "complete"
    return "partial"
