# Release process

Polyglot Swarm does not yet have numbered stable releases — everything lands
on `main` and `main` is expected to always pass `make check`. This document
describes the process for when we cut a version, so it's in place before the
first one rather than invented ad hoc.

## Versioning

The project follows [Semantic Versioning](https://semver.org/). The version
is derived from `src/__init__.py` (`[tool.hatch.version]` in
`pyproject.toml` points at it) — bump it there.

Before 1.0.0, breaking changes may happen in minor releases; this is called
out per-release in `CHANGELOG.md`.

## Changelog discipline

`CHANGELOG.md` follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Every user-visible change (new endpoint, config option, CLI command,
behavior change, bug fix) is added under `[Unreleased]` **in the same PR**
that makes the change — not batched up at release time from memory. Entries
are grouped by phase/feature with a short "why," not just a diff summary;
see existing entries for the expected level of detail.

## Cutting a release

1. Confirm `main` is green: `make ci` (lint, format-check, typecheck, test)
   passes, plus `make benchmark` and `make eval` for anything touching LLM
   behavior.
2. Move the `[Unreleased]` section of `CHANGELOG.md` to a new version
   heading (`## [X.Y.Z] - YYYY-MM-DD`), leaving a fresh empty `[Unreleased]`
   section above it.
3. Bump the version in `src/__init__.py`.
4. Commit as `chore(release): vX.Y.Z`, tag the commit (`git tag vX.Y.Z`), and
   push the tag.
5. Draft a GitHub Release from the tag; the body can largely be the
   corresponding `CHANGELOG.md` section.
6. If publishing to PyPI: build (`python -m build`) and upload
   (`twine upload`) — not yet automated; see the tracking issue if you're
   picking this up.

## Docker images

`docker-compose.yml` builds the image locally from the `Dockerfile` rather
than pulling a published tag today. If/when we publish images to a
registry, tag them `polyglot-swarm:X.Y.Z` and `polyglot-swarm:latest`
matching the Git tag, built via the same `Dockerfile` with no changes.

## Post-release

- Verify the tagged commit still passes `make ci` in a clean checkout (catches
  anything that only worked because of local state).
- Open an issue for anything deferred out of the release so it isn't
  forgotten.
