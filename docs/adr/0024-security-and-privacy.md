# 0024. Security and privacy (Phase 21)

- Status: Accepted
- Date: 2026-09-15

## Context

The plan wants, for a self-hostable product, privacy as a feature: password
hashing (already done, bcrypt), secure sessions/tokens, authorization checks
(already consistent — every route threads the auth-resolved `user_id`, never
a client-supplied one), rate limiting, encrypted secrets, database backups,
user data export/deletion, audit logs, configurable telemetry, and a
local-only mode. Before this phase, bearer tokens were stored raw in SQLite
with no expiry, no rate limiting existed anywhere, no backup mechanism
existed, and there was no way for a user to see or erase everything the
system had stored about them. `cryptography` was already a transitive
dependency (via another package) but unused in `src/`.

## Decision

- **Tokens hashed at rest + expiry**: `src.api.auth` now stores
  `sha256(token)` in the existing `auth_tokens.token` column (SHA-256, not
  bcrypt — the token is already a cryptographically random 256-bit value,
  not a low-entropy human secret, so it needs no salting/slow-hashing) and
  stamps a nullable `expires_at` (migration 0006), driven by
  `settings.token_ttl_hours` (default 30 days). `resolve_token` treats an
  expired token exactly like an unknown one — the caller cannot distinguish
  "never existed" from "expired", the conservative, non-information-leaking
  choice. `purge_expired_tokens` is separate housekeeping, not a security
  boundary (expired tokens are already rejected regardless of whether it
  runs).
- **Rate limiting**: `src.security.rate_limit.RateLimiter`, a small
  in-process fixed-window counter keyed by an arbitrary string (the client
  IP, for the auth routes). No new dependency (no Redis-backed distributed
  limiter) — this is a local-first, single-process deployment; a
  process-global in-memory limiter is the right-sized tool, with the
  explicit trade-off noted that it does not generalize to a
  multi-process deployment. Wired into `/auth/register` (5/60s) and
  `/auth/login` (10/60s) as a 429 response.
- **Encrypted secrets**: `src.security.secrets` wraps Fernet symmetric
  encryption (`cryptography`, already vendored) — `encrypt_secret`/
  `decrypt_secret`/`generate_key`. Deliberately not a secrets manager: it
  answers one question (encrypt/decrypt a string given a key) and leaves key
  custody to the caller.
- **Backups**: `src.security.backup.create_backup` uses SQLite's own online
  backup API (`sqlite3.Connection.backup()`), safe against a live database
  without stopping writers — not a naive file copy. Backups land in
  `{data_dir}/backups/`, timestamp-prefixed so `list_backups` sorts
  chronologically by filename.
- **Audit log**: a new `audit_log` table (migration 0006) via
  `src.security.audit` — append-only by design, generic (`event_type` +
  JSON `detail`) rather than one table per event kind. Wired into
  `/auth/register`/`/auth/login` (success and failure).
- **User data export/deletion**: `src.memory.privacy.export_user_data`/
  `delete_user_data` aggregate every user-keyed store. Getting this right
  required adding a `delete_for_user`(and, for a few stores, an unbounded
  "get all") function to every store module that didn't already have one —
  `vocabulary_db`, `collocations`, `session_history`, `analytics`,
  `sessions`, `skill_state`, `assessments`, `evidence.store`, `experiments`
  (assignments + outcomes, across all experiments), `user_profile`/
  `profiles_db` (both the JSON mirror and the SQLite row), and
  `src.api.auth` (tokens + the account row itself). `model_runs` has no
  `user_id` column at all, so its rows are found via the interaction ids
  recorded in `session_interactions` (Phase 17's link table) — a second use
  for that table beyond tracing. `VectorStore` gained `get_all`/`delete`
  methods (Chroma's native metadata-filtered `get`/`delete`) since it
  previously only supported semantic `query()`.
  - **Audit log is the one deliberate exception**: it is not deleted on
    erasure, since its whole purpose is a trustworthy, append-only security
    record. `anonymize_for_user` instead nulls `user_id` on that user's rows,
    keeping the event/detail/timestamp for security forensics without
    retaining personal linkage — a considered trade-off, not an oversight.
  - Exposed as `GET /api/v1/privacy/export` / `DELETE /api/v1/privacy/data`,
    both **self-service and auth-scoped to the caller only** — there is no
    admin-on-others variant, deliberately, since that would reintroduce
    exactly the authorization gap the rest of the API is careful to avoid.
    Also exposed as `polyglot privacy export/delete` (with a confirmation
    prompt, skippable via `--yes`).
- **Configurable telemetry**: `settings.telemetry_enabled` (default `True`)
  gates whether the FastAPI startup lifespan registers the durable
  `model_runs` persistence sink. The in-process ring buffer
  (`src.llm.telemetry`) always records regardless — this only gates the
  durable, cross-restart sink.
- **Local-only mode**: `settings.local_only` (default `False`). When set,
  `src.llm.factory._build_chain` excludes every hosted provider
  (Claude/Gemini/OpenAI) from the chain regardless of which API keys are
  configured, leaving only Ollama. This makes "no learning data leaves this
  machine" an enforced guarantee rather than a matter of not setting keys —
  verified by constructing a chain with all three hosted keys set and
  `local_only=True` and confirming the resulting chain is `["ollama"]` for
  every tier.

## Consequences

- A leaked database file no longer yields directly replayable bearer tokens,
  and old sessions expire rather than living forever.
- Brute-force/credential-stuffing and registration spam against the auth
  endpoints now have a floor, at the cost of a rate limiter that does not
  span multiple processes — acceptable for the product's local-first,
  single-process deployment model.
- A user can now genuinely see and erase everything the system has recorded
  about them, including model-run telemetry that has no direct `user_id`
  column, in one call each — with each store's contribution reported
  individually so a partial failure is visible rather than silent.
- The rate limiter's process-global state required a test-isolation fix:
  `tests/test_api/conftest.py`'s `client` fixture now resets both limiters,
  since sequential tests previously shared counters through
  `TestClient`'s synthetic client host and produced false 429s — caught
  while writing this phase's own test suite, not a latent bug shipped
  separately.
- `local_only`/`telemetry_enabled` are opt-in changes to `Settings` with
  safe defaults (`local_only=False`, `telemetry_enabled=True`), so no
  existing deployment's behavior changes without an explicit config change.

