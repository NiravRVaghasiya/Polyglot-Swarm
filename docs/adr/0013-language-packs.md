# 0013. Language packs (Phase 10)

- Status: Accepted
- Date: 2026-09-14

## Context

The project claimed "any language with zero configuration," but real language
competence needs explicit, language-specific knowledge (grammar constructions,
frequency, collocations, register, transfer). Phase 4 seeded a grammar taxonomy
under `languages/<code>/grammar/`; Phase 10 formalizes the full pack.

## Decision

- Extract the shared code/root resolution into `src/languages/paths.py`
  (`NAME_TO_CODE`, `REPO_ROOT`, `pack_code`, `pack_dir`) and refactor the
  grammar taxonomy loader onto it (public API unchanged).
- Add a general pack loader `src/languages/pack.py` that assembles a
  `LanguagePack` from `metadata.yaml`, `frequency/frequency.txt`,
  `collocations/collocations.yaml`, and `register/register.yaml`. Every resource
  is optional (a partial pack still loads); loads are cached.
- Seed packs for the three validation languages — Spanish (Romance baseline),
  Polish (high morphology), Italian (Romance, high cognate overlap) — chosen to
  stress the multilingual architecture.

## Consequences

- Generic agent infrastructure stays reusable; language-specific knowledge is
  explicit, versioned, and discoverable.
- Unknown languages degrade to empty packs, so the app still works generically.
- The seed corpora are small; they establish the schema and loader so real
  frequency/collocation data can be dropped in without code changes.
