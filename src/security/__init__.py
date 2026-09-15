"""Security and privacy (Phase 21).

For a self-hostable, local-first product, privacy is a feature: a user should
be able to run the full stack (UI + API + SQLite + Chroma + local LLM/STT/TTS)
without sending learning data to third parties, and trust that their account
and data are handled safely if they do use hosted providers.

Modules:
- :mod:`rate_limit` — a dependency-free, in-process rate limiter for
  authentication endpoints (brute-force / registration-spam mitigation). No
  new third-party dependency: this is a single-process, local-first
  deployment, so a small in-memory limiter is a better fit than pulling in a
  distributed rate-limiting library.
- :mod:`secrets` — envelope encryption for secrets at rest (API keys, or any
  other sensitive config value), built on the already-vendored
  ``cryptography`` package (Fernet) rather than adding a new dependency.
- :mod:`backup` — SQLite database backups (:func:`backup.create_backup`) using
  SQLite's own online backup API, safe to run against a live database.
- :mod:`audit` — an append-only audit log for security-relevant events
  (login, registration, data export/deletion, ...).
"""

from src.security.audit import log_event, recent_events
from src.security.backup import BACKUP_SUFFIX, create_backup, list_backups
from src.security.rate_limit import RateLimiter, RateLimitExceededError
from src.security.secrets import decrypt_secret, encrypt_secret, generate_key

__all__ = [
    "BACKUP_SUFFIX",
    "RateLimitExceededError",
    "RateLimiter",
    "create_backup",
    "decrypt_secret",
    "encrypt_secret",
    "generate_key",
    "list_backups",
    "log_event",
    "recent_events",
]
