# Polyglot Swarm — canonical developer workflow.
#
# These targets are the single source of truth for how the project is built,
# tested, and checked. CI and pre-commit both call into them so that
# "works on my machine" matches "works in CI".
#
# Windows note: `make` is not installed by default. Either use WSL / Git Bash,
# install GNU Make (e.g. `choco install make`), or run the underlying commands
# shown in each recipe directly in PowerShell.

.DEFAULT_GOAL := help
.PHONY: help install install-dev test lint format format-check typecheck \
        benchmark eval eval-real-validate eval-real eval-real-calibrate eval-real-report eval-adaptive eval-speech health results \
        check ci clean lock

PYTHON ?= python

help: ## Show this help.
	@echo "Polyglot Swarm — available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install the package (runtime only).
	$(PYTHON) -m pip install -e .

install-dev: ## Install the package with dev + voice extras.
	$(PYTHON) -m pip install -e ".[all]"

test: ## Run the test suite (deterministic mode, no network).
	POLYGLOT_DETERMINISTIC=1 $(PYTHON) -m pytest

lint: ## Lint with ruff.
	$(PYTHON) -m ruff check .

format: ## Auto-format with ruff.
	$(PYTHON) -m ruff format .

format-check: ## Verify formatting without writing changes.
	$(PYTHON) -m ruff format --check .

typecheck: ## Type-check with mypy (strict).
	$(PYTHON) -m mypy src

benchmark: ## Run the benchmark harness (deterministic).
	POLYGLOT_DETERMINISTIC=1 $(PYTHON) -m benchmarks

eval: ## Run the evaluation harness: grammar/vocabulary/assessment/curriculum.
	POLYGLOT_DETERMINISTIC=1 $(PYTHON) -m evals

eval-real-validate: ## Validate real-model eval datasets (offline).
	$(PYTHON) -m evals.real validate

eval-real: ## Real-model benchmark: make eval-real PROVIDERS=ollama:llama3.1:latest [CONFIG=default] [RUN=id].
	$(PYTHON) -m evals.real run --providers "$(PROVIDERS)" --config "$(or $(CONFIG),default)" $(if $(RUN),--run-id $(RUN),)

eval-real-calibrate: ## Fit grammar calibration maps from a DEV run: make eval-real-calibrate RUN=<dev_run_id>.
	$(PYTHON) -m evals.real calibrate "$(RUN)"

eval-real-report: ## Score a real-model run: make eval-real-report RUN=<run_id>.
	$(PYTHON) -m evals.real report "$(RUN)"

eval-adaptive: ## SIMULATED adaptive-learning evaluation: learner models + planner outcomes.
	$(PYTHON) -m evals.adaptive models --family continuous
	$(PYTHON) -m evals.adaptive models --family bkt
	$(PYTHON) -m evals.adaptive policies --name policies-main

eval-speech: ## Speech benchmark (needs the voice extra; speechocean762 under evals/speech/external).
	$(PYTHON) -m evals.speech speechocean
	$(PYTHON) -m evals.speech synthetic-build
	$(PYTHON) -m evals.speech synthetic
	$(PYTHON) -m evals.speech report

health: ## Report configuration + provider health.
	$(PYTHON) -m src.cli health

results: ## Regenerate docs/results.md from the measurement harnesses (deterministic).
	POLYGLOT_DETERMINISTIC=1 $(PYTHON) -m src.cli results

check: lint format-check typecheck test ## Run every quality gate locally.

ci: check ## Alias used by CI.

lock: ## Regenerate the dependency lockfile.
	$(PYTHON) -m pip install -e ".[all]" && $(PYTHON) ops/relock.py

clean: ## Remove caches and build artifacts.
	$(PYTHON) -c "import shutil,glob,os; [shutil.rmtree(p, ignore_errors=True) for p in ['.ruff_cache','.mypy_cache','.pytest_cache','build','dist'] + glob.glob('**/__pycache__', recursive=True)]"
