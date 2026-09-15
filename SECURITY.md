# Security Policy

## Reporting a vulnerability

Please **do not** open a public GitHub issue for a security vulnerability.

Instead, use GitHub's private vulnerability reporting for this repository
(the "Report a vulnerability" button under the Security tab), or email the
maintainer directly if that isn't available. Include:

- A description of the vulnerability and its potential impact.
- Steps to reproduce (a minimal repro is ideal).
- The affected version/commit.

We'll acknowledge receipt within a few days and keep you updated as we
investigate and fix. Once a fix is released, we'll credit reporters who want
credit in the release notes, unless you ask us not to.

## Supported versions

Polyglot Swarm does not yet have numbered stable releases with a formal
support window — see [`RELEASING.md`](RELEASING.md). Until 1.0, security
fixes land on `main` and we recommend always running the latest commit.

## Scope

Polyglot Swarm is a self-hosted, local-first application. Most deployments
run on infrastructure the operator controls, which changes the threat model
compared to a hosted SaaS:

- **In scope**: vulnerabilities in this codebase itself — auth/token
  handling (`src/api/auth.py`), rate limiting (`src/security/rate_limit.py`),
  secrets-at-rest handling (`src/security/secrets.py`), the privacy
  export/deletion pipeline (`src/memory/privacy.py`), prompt-injection
  handling for scenario/external content (`src/safety/`), and anything that
  could let one user read or modify another user's data through the API.
- **Out of scope**: vulnerabilities in third-party dependencies (report those
  upstream — we'll pick up the fix via a version bump), vulnerabilities that
  require an operator to have already misconfigured their deployment (e.g.
  running the API with no reverse proxy on a public IP with no auth), and
  denial-of-service against a self-hosted instance you don't control the
  scaling of.

## Security-relevant design notes for self-hosters

These are documented in more depth in [`docs/privacy.md`](docs/privacy.md),
but the highlights:

- Bearer tokens are stored **hashed** (SHA-256), never in plaintext, and
  expire after `TOKEN_TTL_HOURS` (default 30 days).
- `LOCAL_ONLY=true` enforces that no learning data is sent to a hosted LLM
  provider, regardless of which API keys happen to be configured.
- The built-in rate limiter on `/auth/login` and `/auth/register` is
  in-process only — if you run multiple API processes behind a load
  balancer, put a real rate limiter (or your reverse proxy's) in front of
  auth endpoints instead of relying on it alone.
- A learner can export or permanently delete their own data via
  `GET /api/v1/privacy/export` / `DELETE /api/v1/privacy/data` (or the
  `polyglot privacy` CLI commands).

If you find a gap between what's documented here and what the code actually
does, that's itself worth a security report.
