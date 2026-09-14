# Contributing to Polyglot Swarm

Thank you for your interest in contributing! This project aims to build the best open-source AI language tutor, and community contributions are essential.

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/polyglot-swarm.git`
3. Install dev dependencies: `pip install -e ".[dev]"`
4. Create a branch: `git checkout -b feature/your-feature`
5. Make your changes
6. Run tests: `pytest`
7. Run linting: `ruff check . && ruff format .`
8. Submit a PR

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
- Format with `ruff format`
- Lint with `ruff check`
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

## Questions?

Open a [Discussion](https://github.com/YOUR_USERNAME/polyglot-swarm/discussions) for questions, ideas, or general chat.
