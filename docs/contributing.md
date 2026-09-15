# Contributing

The full contributor guide — setup, the `make` workflow, code style, commit
conventions, and the PR process — lives at the repository root:
[`CONTRIBUTING.md`](../CONTRIBUTING.md). This page is a short map of the
`docs/` directory so you know where to look before changing something.

## Where to look

| If you're changing... | Read first |
|---|---|
| An agent, the graph, or orchestration | [`architecture.md`](architecture.md) |
| Skill beliefs, CEFR estimation, mastery | [`learner-model.md`](learner-model.md) |
| The evaluator, verifier, or eval/benchmark suites | [`evaluation.md`](evaluation.md) |
| A language pack or cross-language transfer data | [`language-packs.md`](language-packs.md) |
| The LLM abstraction, routing, retries, cost tracking | [`providers.md`](providers.md) |
| Data export/deletion, auth, secrets, rate limiting | [`privacy.md`](privacy.md) |
| Docker, environment config, health/readiness | [`deployment.md`](deployment.md) |
| Anything that changes the system's shape | [`adr/README.md`](adr/README.md) — add an ADR |

## Documentation conventions

- Document what is **actually implemented**, grounded in the code — not
  aspirational design. `DESIGN.md` and `RESEARCH.md` in this directory are
  the original product research and vision; they are not kept in sync with
  the implementation and should not be treated as a spec.
- A structural or architectural decision gets an ADR
  (`docs/adr/NNNN-title.md`, copied from `docs/adr/template.md`) in the same
  PR that makes the change, not as a follow-up.
- User-visible changes (new endpoints, config options, CLI commands, behavior
  changes) get a `CHANGELOG.md` entry under `[Unreleased]`.
- Keep this file and `CONTRIBUTING.md` from drifting apart: setup/workflow
  instructions belong in `CONTRIBUTING.md`; what-is-this-subsystem
  explanations belong here.
