# 0027. Open-source quality (Phase 24)

- Status: Accepted
- Date: 2026-09-15

## Context

The plan calls for the documentation and community infrastructure expected
of a serious open-source project: architecture/subsystem docs, issue and PR
templates, a security policy, a code of conduct, and a release process.
Before this phase, `docs/` contained only the original product research
(`DESIGN.md`, `RESEARCH.md`) and the ADR log — accurate as history, but not
a substitute for grounded documentation of what the system actually does
today, 24 phases later. `CONTRIBUTING.md` (already thorough) had no
companion subsystem docs to point contributors at. There was no `.github/`
directory at all, no `SECURITY.md`, no `CODE_OF_CONDUCT.md`, and no
documented release process — unsurprising, since the project has not yet
cut a numbered release, but worth having in place before the first one
rather than inventing it ad hoc under release pressure.

## Decision

- **New `docs/` pages describe the implementation, not the vision.** Each of
  `architecture.md`, `learner-model.md`, `evaluation.md`,
  `language-packs.md`, `providers.md`, `privacy.md`, `deployment.md` was
  written by reading the actual source (function/class names, concrete file
  paths, real config variables) rather than updating or trusting
  `DESIGN.md`. `DESIGN.md`/`RESEARCH.md` are left as-is and explicitly
  labeled (in the new `contributing.md`) as historical vision documents, not
  a spec — rejected rewriting them in place, since that would destroy the
  historical record of the original research this project was based on.
- **One doc per subsystem, not one large document.** Rejected a single
  monolithic `ARCHITECTURE.md` covering everything — splitting by subsystem
  (learner model, evaluation, language packs, providers, privacy,
  deployment) matches how a contributor actually approaches the codebase:
  by the area they're about to change, per the "where to look" table in
  `docs/contributing.md`.
- **Community files follow well-established conventions rather than bespoke
  text.** `CODE_OF_CONDUCT.md` is the Contributor Covenant 2.1 verbatim
  (attributed), not a custom-written policy — using the standard,
  widely-recognized text is more valuable to contributors than a bespoke
  document that says approximately the same thing. `SECURITY.md` follows
  the shape GitHub's private-vulnerability-reporting feature expects
  (report privately, not via a public issue) and scopes what is/isn't
  considered in-scope for a self-hosted, local-first application
  specifically — a generic SaaS security policy template would not fit this
  product's actual threat model.
- **A release process doc before the first release, not after.**
  `RELEASING.md` documents semantic versioning (version lives in
  `src/__init__.py`, already wired into `pyproject.toml`'s
  `[tool.hatch.version]`), `CHANGELOG.md` discipline (entries added in the
  same PR as the change, not reconstructed at release time), and the
  concrete steps to cut a release. Writing this now, while there is no
  release-time pressure, means the first real release follows a process
  that was thought through calmly rather than invented under time pressure.
- **Cross-linked from the two most-read entry points.** `README.md` gained a
  "Documentation" section linking every new `docs/` page; `CONTRIBUTING.md`
  gained a "Learning the codebase" section with the same links plus pointers
  to `CODE_OF_CONDUCT.md` and `SECURITY.md`. Rejected leaving the new docs
  undiscoverable except by browsing `docs/` directly.

## Consequences

- A new contributor has a grounded starting point for each subsystem instead
  of only the original (now 24-phases-stale) design document and having to
  read source code cold.
- Security reports have a clear, private channel
  (`SECURITY.md`) instead of defaulting to a public GitHub issue, which is
  the most common way a vulnerability gets accidentally disclosed before a
  fix ships.
- The project has documented, reviewable expectations for contributor
  conduct before it needs to enforce them under conflict, and a release
  process it can follow mechanically when the time comes rather than
  deciding one under pressure.
- This phase touched no `src/` or `tests/` code — verified by `ruff check .`,
  `ruff format --check .`, and `mypy src` all remaining clean, and the full
  test suite (1001 tests) passing unchanged.
- Maintaining these docs now carries an ongoing cost: subsystem docs will
  drift from the implementation if not updated alongside future structural
  changes, the same risk `DESIGN.md` already demonstrates. `contributing.md`
  states the expectation that a structural change updates the relevant
  subsystem doc in the same PR, but nothing currently enforces this
  mechanically.
