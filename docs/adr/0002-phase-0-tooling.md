# 0002. Phase 0 stabilization tooling choices

- Status: Accepted
- Date: 2026-09-14

## Context

Phase 0 of the 10/10 plan is "repository stabilization": make the project
trustworthy before adding features. Its acceptance criteria are that
`make test`, `make lint`, `make typecheck`, and `make benchmark` all work from a
clean checkout. The repository already had `pyproject.toml` (hatchling backend),
ruff and mypy configured, a pytest suite, `.env.example`, a pydantic-settings
loader, and a `/health` endpoint — but it lacked a canonical command workflow,
CI, pre-commit hooks, a lockfile, a changelog, ADRs, config validation, a
deterministic test mode, and single-source versioning.

## Decision

We will standardize Phase 0 tooling as follows:

- **Canonical workflow: a `Makefile`.** One source of truth for build/test/lint
  /typecheck/benchmark/health commands; CI and pre-commit call into the same
  underlying tools. (Windows users run the underlying commands directly or via
  WSL/Git Bash; documented in the Makefile header and CONTRIBUTING.)
- **CI: GitHub Actions** on Python 3.12, running ruff (lint + format check),
  mypy (strict on `src`), pytest, and a benchmark smoke run, all with
  `POLYGLOT_DETERMINISTIC=1` so CI needs no API keys and is not flaky.
- **Pre-commit** wiring ruff (with `--fix`) + ruff-format + mypy so local
  commits match CI.
- **Lockfile: `requirements.lock`** produced by `pip freeze --exclude-editable`
  (`make lock`), while `pyproject.toml` remains the source of truth for direct
  dependencies. We use pip's lockfile rather than adopting a new dependency
  manager to avoid churn; this can be revisited (e.g. `uv.lock`) later.
- **Versioning:** single source in `src/__init__.py` (`__version__`), consumed
  by hatchling (`[tool.hatch.version]`), the FastAPI app, and `/health`.
- **Deterministic test mode:** `POLYGLOT_DETERMINISTIC=1` makes
  `get_provider` resolve to a `FakeProvider`, wired at the existing provider
  seam. The root `tests/conftest.py` enables it for the whole suite.
- **Config validation:** `Settings` validates that at least one LLM backend is
  reachable (hosted key, Ollama URL, or deterministic mode) and that
  `.env.example` stays in sync with the schema.

## Consequences

- A clean checkout can be verified with a handful of memorable commands, and CI
  enforces the same gates, blocking regressions.
- Deterministic mode removes the test suite's dependency on live models — a
  prerequisite for the later evaluation harness (Phase 18) and for cheap CI.
- The pip lockfile is simple but does not resolve a full cross-platform graph
  the way `uv`/`poetry` would; ADR revisit is expected if reproducibility needs
  grow.
- Choosing a `Makefile` adds friction for native-Windows contributors, mitigated
  by documenting the raw commands.
