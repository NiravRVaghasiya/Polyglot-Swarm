# 0004. Task-tier routing, structured output, and telemetry (Phase 1)

- Status: Accepted
- Date: 2026-09-14

## Context

The LLM layer exposed a single `generate()` returning plain text, with routing
by capability tier (`primary`/`fast`/`local`) and no structured-output
validation, streaming, token counting, or telemetry. The plan (Phase 1) wants
providers to support `generate_structured`/`stream`/`count_tokens`, routing by
*task* rather than one-agent-one-provider, schema-validated output, graceful
fallback, recorded cost/latency, and an OpenAI provider — all without any agent
importing a vendor SDK directly. A frozen contract (`get_provider(tier)`
returning an object with `async generate(...)`) is relied on by ten agents and
the test suite.

## Decision

Extend rather than replace:

- Add `generate_structured()`, `stream()`, and `count_tokens()` to
  `LLMProvider` as **non-abstract defaults** built on `generate()`, so every
  existing provider gains them for free and the `generate()` signature is
  unchanged.
- Add task tiers (`critical_reasoning`, `fast_extraction`,
  `cheap_classification`, `local_private`) that **map onto** the capability
  tiers via `src/llm/router.resolve_tier`, instead of renaming tiers.
- Add `src/llm/schemas.py` (Pydantic models + tolerant `parse_structured`) and
  `src/llm/telemetry.py` (latency/token/cost records with pluggable sinks),
  wiring telemetry into `RoutingProvider.generate`.
- Add `src/llm/openai.py`; it joins the routing chain only when
  `OPENAI_API_KEY` is set, preserving the existing three-provider chain by
  default.

## Consequences

- Agents can adopt validated structured output and richer routing incrementally;
  nothing they do today breaks.
- Cost/latency/token usage is observable centrally (feeds Phase 17/22).
- The capability-tier chain contract (`{claude, gemini, ollama}`) is preserved
  in tests; OpenAI is additive.
- `parse_structured` returning `None` (rather than raising) makes abstention/
  fallback the natural default for malformed output.
