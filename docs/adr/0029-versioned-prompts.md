# 0029. Versioned prompt registry (Gate B)

- Status: Accepted
- Date: 2026-09-15

## Context

The plan's Gate B requires "versioned prompts". The audit found this was an
over-claim: `src/llm/prompts/__init__.py` had a `render(template_name, **ctx)`
that loaded `.jinja2` files by raw filename, with no version tags, no
registry, and no way to know or pin which prompt version produced an output.
Worse, it was inconsistent — the four most important agent prompts (grammar,
vocabulary, conversation, review) were not templates at all but inline Python
string constants (`GRAMMAR_PROMPT`, `VOCABULARY_PROMPT`,
`SYSTEM_PROMPT_TEMPLATE`, `_REVIEW_PROMPT`), so roughly half the agents
bypassed the template system entirely. "Prompts are in git" is not the same
as "versioned prompts".

## Decision

- **A registry as the single source of truth.**
  `src/llm/prompts/registry.py` defines `PROMPT_REGISTRY`, a manifest mapping
  each logical prompt name to a `PromptSpec(name, version, template)`.
  `render_prompt(name, version=None, **ctx)` resolves the current (or a pinned)
  version, renders it, and returns a `RenderedPrompt` that carries its own
  `name` and `version` — so the version is knowable at the call site and
  recordable in telemetry. `_versioned_template_name` maps a pinned older
  version to the conventional `<name>_v<N>.jinja2`, so bumping a prompt means
  adding a new file and updating one registry line, with the old version still
  on disk. This makes a prompt change auditable and reversible.
- **Migrate the inline prompts, don't just wrap them.** The four inline
  string constants were converted to versioned `*_v1.jinja2` templates
  (`{var}` → `{{ var }}`, doubled `{{ }}` literal JSON braces → `{ }`) and the
  constants removed, so *every* agent now renders through the one versioned
  path. Rejected leaving them inline with a version comment — that would keep
  the inconsistency the audit flagged.
- **Preserve exact behavior.** The conversation prompt interpolates
  pre-rendered sub-blocks (the delimited `<SCENARIO>` block, the untrusted-data
  notice, pedagogical steering, role disclaimer); these are passed as template
  variables and, with `autoescape=False`, inserted verbatim — so injected
  braces in untrusted scenario content are inert data, not re-parsed markup,
  and the injection-hardening from ADR 0023 is unchanged. Verified by the
  existing `test_conversation_safety` tests (which assert those exact tokens)
  passing unmodified.
- **Keep `render()` as a back-compat shim.** The old
  `render("name.jinja2", ...)` still works (returns text), so any caller not
  yet migrated is unaffected. New code uses `render_prompt` by registered
  name.

## Consequences

- Every agent prompt now has a version that is knowable and pinnable, and
  they all go through one path — the concrete thing "versioned prompts"
  should mean. A future A/B of prompt versions is a new `*_v2.jinja2` plus a
  registry bump, not a destructive edit.
- The prompt *version* is available (`RenderedPrompt.version`) but is not yet
  threaded into the `model_runs` telemetry record — doing so would change
  every `generate()` signature. Recording the version per call is a
  deliberately-deferred extension; the registry already makes it retrievable.
- Prompt text now lives entirely in `.jinja2` files rather than partly in
  Python, so a prompt change no longer touches agent code — at the small cost
  that reading an agent no longer shows its prompt inline (the registry name
  points to the file).
