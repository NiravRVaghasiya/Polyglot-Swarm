# Security and privacy review (Phase 5)

Review date: 2026-11-07. This review describes the controls in the code and
how each is tested. It is **not a legal or regulatory compliance
assessment**, and Polyglot Swarm makes no compliance claim. The obligations
an operator must assess are listed at the end.

## Access control

| Control | Implementation | Verified by |
|---|---|---|
| Authentication | bcrypt passwords (minimum length 8 by default; configurable); random 256-bit bearer tokens stored only as SHA-256 hashes; expiry (`TOKEN_TTL_HOURS`) | `test_auth_security.py`, `test_security.py` |
| Authorization | every API route needs a valid token; every read and write is scoped to the caller's `user_id`; session lookups key on `(user_id, session_id)` | `test_security.py::TestIsolation` (sessions, chat, end, submissions, cost, trace, export) |
| Roles | one role: a learner, who acts only on their own data. There are no admin API endpoints. Operator actions go through the CLI on the host (`polyglot ops ...`), which requires host access. | — (by design) |
| Tenancy | single-tenant deployment; isolation is per learner account | as above |
| Gradio UI | no per-learner accounts, so it is not part of the production profile and refuses to start in staging/production without `GRADIO_AUTH` | `test_security.py::test_gradio_requires_credentials_in_production` |
| Metrics | `/metrics` needs `METRICS_TOKEN` (constant-time comparison); required in staging/production | `test_metrics_require_the_token_when_configured` |

## Input handling and abuse protection

| Risk | Control |
|---|---|
| Oversized requests | 16 MB body limit (413), from `Content-Length` and while streaming; audio limits from ADR-0034 (10 MB, 120 s, formats sniffed) |
| Credential stuffing, registration spam | per-IP login and registration rate limits (Phase 21) |
| Cost abuse, runaway agents | per-user work rate limit (429 with `Retry-After`); per-user and global daily LLM budgets; per-turn LLM call cap |
| Duplicate submissions | `Idempotency-Key` on chat, review submission and assessments |
| SQL injection | parameterised queries throughout; the 20 places that build SQL text interpolate only fixed identifiers and were reviewed (marked `noqa: S608`). The ruff `S` rules run in CI, so a new string-built query is flagged. |
| Prompt injection | learner text is wrapped as untrusted data in prompts (ADR-0023); structured outputs are schema-validated, and invalid output yields no evidence |
| IDOR | see the isolation tests above |
| Error leakage | unhandled errors return `{"detail": "internal error", "request_id": ...}`; readiness reports exception *types* only |
| Clickjacking, MIME sniffing | API: `X-Frame-Options: DENY`, `nosniff`, a `default-src 'none'` CSP, `no-store` on API responses, HSTS in staging/production. Web app: CSP, `DENY`, `nosniff`, no `X-Powered-By`. |
| Token theft through XSS | the token is in `localStorage` (a residual risk). The web app's CSP `connect-src` allows only its own origin and the API, so an injected script cannot send a token elsewhere. |

## Secrets and supply chain

- **Secrets.** Secrets come only from the environment (`.env` or
  `.env.production` on the host; both are git-ignored). Startup validation
  rejects unsafe production settings.
- **Git history.** Scanned for provider keys and private keys: none found.
  `python -m src.security.secret_scan` runs in CI.
- **Python dependencies.**
  - They are pinned in `requirements.lock`, regenerated from the tested
    environment, and the image and CI install with it as a constraints
    file.
  - `pip-audit` runs in CI through `src.security.dependency_audit`. Two
    exceptions are accepted, by exact version and with a review-by date,
    in `ops/security/accepted-vulnerabilities.yml`:
    - **pillow 12.3.0** — every gradio release requires `pillow<13`; only
      the Gradio UI reaches pillow, and it is not deployed in production;
    - **chromadb 1.5.9** — the advisories affect its server and RBAC
      modes; it is used embedded only, and no fix exists.
  - Thirteen vulnerable packages were found in the previous lockfile; the
    other eleven were upgraded.
- **Frontend dependencies.**
  - Locked in `package-lock.json` (added in this phase) and installed with
    `npm ci`.
  - `npm audit --omit=dev --audit-level=critical` runs in CI.
  - One known high-severity advisory: PostCSS inside Next's build tooling.
    It affects build-time CSS processing, not the running app. The fix is a
    Next major upgrade, listed as follow-up work.
- **Container.** Runs as a non-root user with a read-only root filesystem
  (production compose), with all capabilities dropped and
  `no-new-privileges`.

## Data classification and retention

| Class | Examples | Where | Retention | Deletion |
|---|---|---|---|---|
| **Credentials** | password hashes, token hashes | `users`, `auth_tokens` | account lifetime; tokens until expiry (purged by maintenance) | account deletion |
| **Learner content** | chat messages, typed answers, transcripts | `session_history`, `active_sessions` snapshots (cleared at finalization), `media_submissions.report` | account lifetime | in-app export and delete |
| **Raw audio** | speaking recordings | not stored by default; with explicit `retain_audio` consent, `media/<user>/` | **30 days**, then purged | purge, submission delete, account delete |
| **Derived learning data** | evidence, mastery, plans, reviews, adaptive decisions | `evidence`, `skill_states`, `vocabulary`, `adaptive_decisions`, … | account lifetime (it is the learning record) | account delete |
| **Operational telemetry** | model runs (tokens, latency, cost), daily usage counters, idempotency keys | `model_runs`, `llm_usage_daily` (90 days), `idempotency_keys` (24 h) | as listed | maintenance; account delete covers per-user rows |
| **Logs** | access lines, errors | container stdout (5 × 20 MB rotation) | rotation | not per user; they hold no content |
| **Backups** | full copies of the above | `/data/backups/` and the off-host copy | 14 sets (about 14 days) | expire by retention; **an account deletion is not propagated into existing backups** (it persists at most until those sets expire) |

**Minimisation.**

- Logs and metrics carry no learner content, tokens or audio. Metrics carry
  no user ids, and route labels are templates.
- Evidence stores no transcript text (ADR-0034).
- Provider requests contain only what the task needs: the conversation
  context for the tutor, and the learner's sentence for analysis.

## Third-party data flows

| Provider | When | What leaves the server |
|---|---|---|
| Anthropic / Google / OpenAI (hosted LLMs) | chat turns, analysis, session end, when configured | the learner's messages, recent conversation context and the system prompts; no account identifiers |
| Ollama (local) | if configured | nothing leaves the operator's infrastructure |
| Microsoft Edge TTS | listening audio, voice replies | the text to speak: task scripts, or the tutor's reply; no learner identifiers |
| Whisper (local) | speaking assessment | nothing leaves the server |

**`LOCAL_ONLY=true`** refuses any hosted LLM provider. That is the
configuration for an operator who may not send learner text to third
parties. Each hosted provider's own retention and training terms apply to
what is sent; the operator must review them.

## Obligations to assess before serving real learners (not done here)

- **Data-protection law** (for example GDPR or UK GDPR for EU/UK learners):
  - a lawful basis;
  - a privacy notice;
  - data processing agreements with the hosted providers;
  - international transfer mechanisms;
  - whether the evidence-based learner model counts as profiling.
- **Children.** Learners may be minors, and Phase 4 already measured weaker
  speech assessment for children. COPPA (US), age-appropriate design codes
  (UK/EU) and parental consent need a documented assessment before minors
  are admitted.
- **Biometric and voice data rules.** Voice recordings may count as
  biometric or sensitive data in some jurisdictions. Retention is
  consent-based and short, but the classification needs legal review.
- **Accessibility and education-sector rules,** if the product is sold to
  schools.
