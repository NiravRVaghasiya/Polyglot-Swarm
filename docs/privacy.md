# Privacy and data handling

Polyglot Swarm is designed to be self-hostable with privacy as an enforced
property, not a policy statement. This document describes what data is
collected, where it lives, and the controls available to a learner or
operator.

## Where data lives

**SQLite** (`settings.db_path`, default `./data/polyglot.db`) is the source
of truth for everything relational. Tables of note (see
`src/memory/schema.py` for the full DDL): `users`, `auth_tokens`,
`profiles`, `sessions`, `skill_states`, `learner_state_snapshots`,
`evidence`, `assessments`, `experiments` / `experiment_assignments` /
`outcomes`, `model_runs`, `error_patterns`, `learning_sessions`,
`collocations`, `session_interactions` (the correlation table linking a
session to its model runs), `audit_log`.

**ChromaDB** (`settings.chroma_path`, default `./data/chroma`) holds four
semantic-search collections: `vocabulary`, `grammar_rules`, `conversations`,
`cultural_notes` (`src/memory/vector_store.py`).

**Flat files**: per-user profile JSON under `settings.profiles_dir`
(default `./data/user_profiles`).

Migrations are additive-only — `schema.init_all()` provisions/extends the
schema at startup, never drops data.

## Authentication

`src/api/auth.py`: passwords are bcrypt-hashed. Bearer tokens are generated
with `secrets.token_urlsafe(32)`, and the **raw token is never persisted** —
only its SHA-256 hash is stored in `auth_tokens`, and the raw value is
returned to the client exactly once (at register/login). Tokens expire after
`settings.token_ttl_hours` (default 30 days); `resolve_token()` treats an
expired token identically to an unknown one, so no information about "this
token existed but expired" leaks to a caller presenting a stale token.

Login and registration are rate-limited (`src/security/rate_limit.py`'s
`RateLimiter`, an in-process fixed-window counter — 10 calls/60s for login,
5/60s for registration) to blunt credential-stuffing and registration spam.
This is explicitly **not** safe for a multi-process deployment (each process
has its own counters); accepted trade-off for a local-first, mostly
single-user product.

## Local-only mode

`settings.local_only` (env `LOCAL_ONLY=true`) is the main privacy lever: the
LLM provider factory excludes every hosted provider (Claude, Gemini, OpenAI)
from every tier's routing chain **regardless of which API keys are
configured**, leaving only local Ollama. If Ollama is also unavailable, LLM
calls fail loudly rather than silently falling back to a hosted vendor. See
[`providers.md`](providers.md).

`settings.telemetry_enabled` (default `true`) gates only whether LLM-call
telemetry (latency/tokens/estimated cost — no message content) is persisted
to the `model_runs` table across restarts; the in-memory ring buffer used
for the current process's cost/health reporting keeps working either way.

## Self-service export and deletion

`src/memory/privacy.py`:

- **`export_user_data(user_id)`** aggregates every user-scoped store —
  profile, vocabulary, collocations, conversation turns, grammar error
  patterns, learning sessions, skill beliefs, assessments, evidence,
  experiment participation, model-run telemetry (via the observability link
  table), and cultural notes from ChromaDB — into one JSON-serializable
  dict.
- **`delete_user_data(user_id)`** deletes from all of the above plus the
  account's auth tokens and the account row itself. Each store's deletion is
  wrapped individually so one broken store cannot abort the rest; the
  function returns a per-store report of what succeeded.
- The **audit log is deliberately not deleted** on erasure —
  `anonymize_for_user` nulls the `user_id` on audit rows instead, keeping the
  security event itself (an append-only record design: "someone did X at
  time T" stays true even after the "someone" is anonymized).

Exposed as:

- `GET /api/v1/privacy/export`, `DELETE /api/v1/privacy/data` — self-service,
  auth-scoped to the caller only (no admin-on-others endpoint exists).
- `polyglot privacy export` / `polyglot privacy delete` — the CLI
  equivalents.

## Secrets and backups

`src/security/secrets.py` provides Fernet-based `encrypt_secret`/
`decrypt_secret` for at-rest secrets — a helper, not a secrets manager; the
caller owns key storage. `src/security/backup.py` uses SQLite's online
backup API (`create_backup`/`list_backups`). `src/security/audit.py`
provides the append-only audit table and `recent_events()`/
`anonymize_for_user()`. All three are exposed via `polyglot security
backup` / `backups` / `audit`.

## What is never sent to a third party in local-only mode

With `local_only=true` and Ollama configured: conversation text, grammar
analysis, vocabulary extraction, cultural notes, and every other LLM call
route to the local model only. Nothing about a learner's messages, errors,
or progress is transmitted to Anthropic, Google, or OpenAI. The SQLite
database and ChromaDB directory are the only places learning data is
written, both under `settings.data_dir` (or the mounted `/data` volume in
the Docker image) — nothing else.
