# Contributing to Polyglot Swarm

Thank you for your interest in contributing! This project aims to build the best open-source AI language tutor, and community contributions are essential.

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/NiravRVaghasiya/Polyglot-Swarm.git`
3. Install dev dependencies: `make install-dev` (or `pip install -e ".[all]"`)
4. Install the git hooks: `pre-commit install`
5. Create a branch: `git checkout -b feature/your-feature`
6. Make your changes
7. Run every quality gate: `make check`
8. Submit a PR

### Development workflow

The `Makefile` is the single source of truth for how the project is built and
checked; CI runs the same gates. Common targets:

| Command | What it does |
|---------|--------------|
| `make install-dev` | Install the package with dev + voice extras |
| `make test` | Run the test suite (deterministic mode, offline) |
| `make lint` | Lint with ruff |
| `make format` | Auto-format with ruff |
| `make typecheck` | Type-check with mypy (strict) |
| `make benchmark` | Run the benchmark harness |
| `make health` | Report configuration + provider health |
| `make check` | Run lint + format-check + typecheck + test |
| `make lock` | Regenerate `requirements.lock` |

**Windows:** `make` is not installed by default. Use WSL / Git Bash, install
GNU Make (`choco install make`), or run the underlying command shown in each
Makefile recipe directly in PowerShell (e.g. `python -m pytest`).

**Offline / no API keys:** the test suite and benchmarks run in *deterministic
mode* (`POLYGLOT_DETERMINISTIC=1`), which routes all LLM calls to a fake
provider — no keys or network required. Set a real provider key in `.env` only
when you want to exercise live models.

### Architecture decisions

Significant structural changes should be accompanied by an Architecture Decision
Record in [`docs/adr/`](docs/adr/README.md). Copy `docs/adr/template.md`, fill
it in, and add it to the index.

### Learning the codebase

Before changing a subsystem, read the doc for it under [`docs/`](docs/contributing.md):
[`architecture.md`](docs/architecture.md) (agents, the graph, reliability),
[`learner-model.md`](docs/learner-model.md) (mastery/CEFR), [`evaluation.md`](docs/evaluation.md)
(the evaluator agent + eval harness), [`language-packs.md`](docs/language-packs.md),
[`providers.md`](docs/providers.md) (the LLM abstraction, routing, retries),
[`privacy.md`](docs/privacy.md), and [`deployment.md`](docs/deployment.md).
These describe what's actually implemented, not the original product research
in `docs/DESIGN.md`.

## Easy First Contributions

### Add a New Scenario

Scenarios are YAML files in `src/scenarios/definitions/{language}/`. See existing scenarios for the format:

```yaml
scenario:
  id: "es_pharmacy"
  title: "At the Pharmacy"
  language: "es"
  cefr_min: "A2"
  cefr_max: "B1"
  # ... see docs/scenarios.md for full spec
```

### Add Grammar Rules

Grammar rules live in `data/grammar_rules/{language}/`. Each file defines patterns and corrections.

### Improve Frequency Lists

Word frequency data in `data/frequency_lists/` helps the vocabulary agent prioritize high-value words.

### Write Tests

We aim for >80% coverage. Tests go in `tests/` mirroring the `src/` structure.

## Development Guidelines

### Code Style

- Python 3.12+ (use modern syntax: `|` for union types, match/case, etc.)
- Format with `ruff format` (or `make format`)
- Lint with `ruff check` (or `make lint`)
- Type-check with `mypy src` (or `make typecheck`)
- Type hints required on all public functions
- Docstrings (Google style) on all public functions

### Architecture Principles

1. **Agents are independent** — each agent should work in isolation for testing
2. **State flows through LangGraph** — don't use globals or singletons
3. **Memory is explicit** — all persistence goes through the memory layer
4. **LLM calls are abstracted** — never call an LLM directly; use the provider layer
5. **Scenarios are data** — new scenarios should never require code changes

### Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(grammar): add Polish genitive case detection
fix(srs): correct FSRS interval calculation for first review
docs(scenarios): add format specification
test(agents): add conversation agent unit tests
```

### Pull Request Process

1. Update documentation if behavior changes
2. Add tests for new functionality
3. Ensure all tests pass
4. Update CHANGELOG.md
5. Request review from a maintainer

## Areas We Need Help

- 🇵🇱 **Polish language expertise** — grammar rules, case detection, aspect pairs
- 🇪🇸 **Spanish language expertise** — regional variants, subjunctive patterns
- 🇮🇹 **Italian language expertise** — passato/imperfetto rules, regional differences
- 🎤 **Voice/audio** — Whisper integration, pronunciation scoring
- 📊 **Frontend** — React dashboard for progress visualization
- 🧪 **Testing** — Property-based tests for SRS scheduling
- 📝 **Documentation** — Tutorials, guides, architecture docs

## Code of Conduct

Be kind, constructive, and patient. We're all here to learn — both languages and code.
See [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) for the full policy and how to report a concern.

## Security

Found a security issue? Please don't open a public issue — see
[`SECURITY.md`](SECURITY.md) for how to report it privately.

## Questions?

Open a [Discussion](https://github.com/NiravRVaghasiya/Polyglot-Swarm/discussions) for questions, ideas, or general chat.
