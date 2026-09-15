"""Central schema owner and migration runner for the SQLite database.

Before Phase 2, DDL was scattered across stores, each with its own idempotent
``init_db()`` and no notion of schema version. That is fine for additive
``CREATE TABLE IF NOT EXISTS`` but offers no safe path for evolving columns or
ordering changes. This module adds:

- a single :func:`init_all` that provisions every table (existing stores plus
  the new Phase 2 canonical tables) from a clean database, and
- an ordered, versioned migration runner keyed on SQLite's ``PRAGMA
  user_version``, so upgrades apply exactly once and in order.

Existing per-store ``init_db()`` functions are left in place and still work;
:func:`init_all` simply calls them so there is one entry point that guarantees
the full schema. New code should call :func:`init_all` (or its convenience
alias imported by the store modules) rather than relying on lazy per-table
creation.

Design constraints honored:
- Migrations are **additive and safe** (create tables, add columns/indexes);
  no destructive drops or rewrites happen automatically.
- Everything runs inside the shared :func:`src.memory.db.get_connection`
  transaction semantics.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from sqlite3 import Connection

from src.memory.db import get_connection

logger = logging.getLogger("polyglot.memory.schema")

# The schema version this code expects. Bump when you add a migration.
SCHEMA_VERSION = 6


# --------------------------------------------------------------------------- #
# Canonical DDL for the Phase 2 tables (the ones that did not exist before).
# Existing tables (users, auth_tokens, vocabulary, conversation_turns,
# error_patterns, learning_sessions) remain owned by their store modules and
# are created via _init_existing_stores() below.
# --------------------------------------------------------------------------- #

_PHASE2_SCHEMA = """
-- Learner profile as the SQLite source of truth (mirrors the JSON profile).
CREATE TABLE IF NOT EXISTS profiles (
    user_id          TEXT PRIMARY KEY,
    native_language  TEXT NOT NULL DEFAULT 'English',
    target_languages TEXT NOT NULL DEFAULT '[]',   -- JSON list
    cefr_by_language TEXT NOT NULL DEFAULT '{}',    -- JSON object
    goals            TEXT NOT NULL DEFAULT '[]',    -- JSON list
    interests        TEXT NOT NULL DEFAULT '[]',    -- JSON list
    preferences      TEXT NOT NULL DEFAULT '{}',    -- JSON object
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

-- First-class session lifecycle records (distinct from the metrics summary in
-- learning_sessions). Keyed by session_id == LangGraph thread id.
CREATE TABLE IF NOT EXISTS sessions (
    session_id  TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    language    TEXT NOT NULL,
    mode        TEXT NOT NULL DEFAULT 'conversation',
    scenario_id TEXT,
    status      TEXT NOT NULL DEFAULT 'active',   -- active | completed | abandoned
    started_at  TEXT NOT NULL,
    ended_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user_lang ON sessions(user_id, language);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(user_id, status);

-- Per-skill competence snapshots over time (the learner model's belief layer).
CREATE TABLE IF NOT EXISTS skill_states (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    language    TEXT NOT NULL,
    skill       TEXT NOT NULL,        -- speaking|listening|reading|writing|grammar|vocabulary|...
    mastery     REAL NOT NULL DEFAULT 0.0,   -- 0.0 .. 1.0
    uncertainty REAL NOT NULL DEFAULT 1.0,   -- 0.0 .. 1.0
    sample_size INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL,
    UNIQUE(user_id, language, skill)
);
CREATE INDEX IF NOT EXISTS idx_skill_user_lang ON skill_states(user_id, language);

-- Immutable learner-state snapshots for longitudinal analysis / rollback.
CREATE TABLE IF NOT EXISTS learner_state_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    language    TEXT NOT NULL,
    snapshot    TEXT NOT NULL,        -- JSON blob of the learner model state
    reason      TEXT,                 -- e.g. "session_end", "assessment"
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshot_user_lang ON learner_state_snapshots(user_id, language);

-- Structured evidence events (Phase 3 writes here; created now so the schema is
-- complete and migrations stay ordered).
CREATE TABLE IF NOT EXISTS evidence (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id       TEXT UNIQUE NOT NULL,
    user_id        TEXT NOT NULL,
    language       TEXT NOT NULL,
    session_id     TEXT,
    interaction_id TEXT,
    event_type     TEXT NOT NULL,     -- GRAMMAR_ERROR, VOCAB_PRODUCED, ...
    skill          TEXT,
    item_id        TEXT,              -- e.g. construction name or lemma
    observed       TEXT,
    expected       TEXT,
    assessment     TEXT,              -- correct|incorrect|awkward|abstain|...
    confidence     REAL NOT NULL DEFAULT 1.0,
    source         TEXT,              -- model/component version, e.g. "grammar-v3"
    payload        TEXT,              -- JSON blob of extra structured detail
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidence_user_lang ON evidence(user_id, language);
CREATE INDEX IF NOT EXISTS idx_evidence_type ON evidence(user_id, event_type);
CREATE INDEX IF NOT EXISTS idx_evidence_session ON evidence(session_id);

-- CEFR / skill assessments with confidence + sample size.
CREATE TABLE IF NOT EXISTS assessments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      TEXT NOT NULL,
    language     TEXT NOT NULL,
    skill        TEXT,                -- NULL = overall
    cefr         TEXT,
    score        REAL,
    confidence   REAL NOT NULL DEFAULT 0.0,
    sample_size  INTEGER NOT NULL DEFAULT 0,
    method       TEXT,                -- e.g. "assessment-agent-v1"
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assessment_user_lang ON assessments(user_id, language);

-- Learning-science experiments and variant assignments.
CREATE TABLE IF NOT EXISTS experiments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT UNIQUE NOT NULL,
    description TEXT,
    variants    TEXT NOT NULL DEFAULT '[]',   -- JSON list of variant names
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS experiment_assignments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment    TEXT NOT NULL,
    user_id       TEXT NOT NULL,
    variant       TEXT NOT NULL,
    assigned_at   TEXT NOT NULL,
    UNIQUE(experiment, user_id)
);

-- Observability: one row per LLM call (telemetry sink target).
CREATE TABLE IF NOT EXISTS model_runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    provider       TEXT NOT NULL,
    tier           TEXT,
    model          TEXT,
    operation      TEXT NOT NULL DEFAULT 'generate',
    latency_ms     REAL NOT NULL DEFAULT 0,
    input_tokens   INTEGER NOT NULL DEFAULT 0,
    output_tokens  INTEGER NOT NULL DEFAULT 0,
    cost_usd       REAL NOT NULL DEFAULT 0,
    success        INTEGER NOT NULL DEFAULT 1,
    error          TEXT,
    interaction_id TEXT,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_model_runs_provider ON model_runs(provider);
"""


# Phase 5: collocations as first-class learning objects (e.g. "tomar una
# decisión"). A collocation is more than the sum of its words; it is tracked
# and scheduled like a vocabulary item.
_COLLOCATIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS collocations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        TEXT NOT NULL,
    language       TEXT NOT NULL,
    phrase         TEXT NOT NULL,       -- e.g. "tomar una decisión"
    translation    TEXT DEFAULT '',
    pattern        TEXT DEFAULT '',     -- e.g. "verb + noun"
    cefr_level     TEXT DEFAULT '',
    register       TEXT DEFAULT '',
    times_seen     INTEGER DEFAULT 0,
    times_produced INTEGER DEFAULT 0,
    mastery        REAL DEFAULT 0.0,
    card_state     TEXT,
    next_review    TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    UNIQUE(user_id, language, phrase)
);
CREATE INDEX IF NOT EXISTS idx_colloc_user_lang ON collocations(user_id, language);
"""


# Phase 17 observability: correlate a session's turns with the interaction ids
# under which they ran. ``model_runs`` records ``interaction_id`` but not
# ``session_id``; this link table lets the trace assembler join a session's
# model runs (and any per-turn evidence) without adding a session column to the
# hot telemetry-write path.
_SESSION_INTERACTIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS session_interactions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT NOT NULL,
    user_id        TEXT,
    interaction_id TEXT NOT NULL,
    turn_index     INTEGER,
    created_at     TEXT NOT NULL,
    UNIQUE(session_id, interaction_id)
);
CREATE INDEX IF NOT EXISTS idx_session_interactions_session
    ON session_interactions(session_id);
"""


# Phase 21 security: an append-only audit log for security-relevant events
# (login, registration, data export/deletion, backups, ...). Deliberately
# generic (event_type + a JSON detail blob) rather than one table per event
# kind, since the set of auditable events is expected to grow.
_AUDIT_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,       -- e.g. "login", "register", "data_export"
    user_id    TEXT,                -- NULL for events with no associated user
    detail     TEXT NOT NULL DEFAULT '{}',  -- JSON blob
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_log_user ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_type ON audit_log(event_type);
"""


# Phase 19 learning-science experiment platform: measured outcomes for an
# experiment assignment at a point in the study (pre-test, immediate
# post-test, 1/7/30-day delayed test, ...). Kept separate from ``assessments``
# because an outcome is explicitly tied to an experiment + measurement point,
# not a general-purpose CEFR snapshot (though it may *carry* one in payload).
_OUTCOMES_SCHEMA = """
CREATE TABLE IF NOT EXISTS outcomes (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment        TEXT NOT NULL,
    user_id           TEXT NOT NULL,
    variant           TEXT NOT NULL,
    measurement_point TEXT NOT NULL,     -- pre_test|intervention|immediate_post|
                                          -- delayed_1d|delayed_7d|delayed_30d
    metric            TEXT NOT NULL,     -- e.g. "overall_cefr_ordinal", "mastery:grammar"
    value             REAL NOT NULL,
    payload           TEXT NOT NULL DEFAULT '{}',  -- JSON blob of extra detail
    recorded_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outcomes_experiment ON outcomes(experiment, user_id);
CREATE INDEX IF NOT EXISTS idx_outcomes_point ON outcomes(experiment, measurement_point);
"""


def _init_existing_stores() -> None:
    """Create the pre-Phase-2 tables via their owning modules' ``init_db()``.

    Imported lazily to avoid import cycles and to keep each store the owner of
    its own DDL.
    """
    from src.api import auth
    from src.memory import analytics, session_history, vocabulary_db

    auth.init_db()
    vocabulary_db.init_db()
    session_history.init_db()
    analytics.init_db()


# --------------------------------------------------------------------------- #
# Migrations
# --------------------------------------------------------------------------- #

Migration = Callable[[Connection], None]


def _migration_0001_baseline(conn: Connection) -> None:
    """Baseline: ensure all existing store tables exist. (No-op if present.)"""
    # Existing stores are created outside this connection by
    # _init_existing_stores(); nothing extra to do here. Kept so version 1 is a
    # named, ordered step.
    return None


def _migration_0002_phase2_tables(conn: Connection) -> None:
    """Create the Phase 2 canonical tables (profiles, sessions, evidence, ...)."""
    conn.executescript(_PHASE2_SCHEMA)


def _existing_columns(conn: Connection, table: str) -> set[str]:
    """Return the set of column names on ``table``."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


def _migration_0003_vocab_dimensions(conn: Connection) -> None:
    """Add Phase 5 multi-dimensional mastery columns to the vocabulary table.

    Additive and idempotent: only columns that are missing are added, so this
    is safe whether the table was created fresh (with the new _SCHEMA) or
    predates Phase 5. Also adds the collocations table.
    """
    from src.memory.vocabulary_db import _PHASE5_COLUMNS

    existing = _existing_columns(conn, "vocabulary")
    for column, ddl in _PHASE5_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE vocabulary ADD COLUMN {column} {ddl}")

    conn.executescript(_COLLOCATIONS_SCHEMA)


def _migration_0004_session_interactions(conn: Connection) -> None:
    """Create the Phase 17 session<->interaction link table.

    Additive and idempotent (``CREATE TABLE IF NOT EXISTS``).
    """
    conn.executescript(_SESSION_INTERACTIONS_SCHEMA)


def _migration_0005_outcomes(conn: Connection) -> None:
    """Create the Phase 19 experiment-outcomes table.

    Additive and idempotent (``CREATE TABLE IF NOT EXISTS``).
    """
    conn.executescript(_OUTCOMES_SCHEMA)


def _migration_0006_security(conn: Connection) -> None:
    """Phase 21 security hardening: token expiry + an audit log.

    Additive: adds a nullable ``expires_at`` column to the existing
    ``auth_tokens`` table (only if missing, so this is safe whether the table
    predates this migration or was just created) and a new ``audit_log``
    table. Token *hashing* at rest needs no schema change — it is a change to
    what value ``src.api.auth`` stores in the existing ``token`` column
    (a SHA-256 hash instead of the raw token), not a new column.
    """
    existing = _existing_columns(conn, "auth_tokens")
    if "expires_at" not in existing:
        conn.execute("ALTER TABLE auth_tokens ADD COLUMN expires_at TEXT")
    conn.executescript(_AUDIT_LOG_SCHEMA)


# Ordered migrations. Index i (1-based) upgrades user_version from i-1 to i.
_MIGRATIONS: list[Migration] = [
    _migration_0001_baseline,
    _migration_0002_phase2_tables,
    _migration_0003_vocab_dimensions,
    _migration_0004_session_interactions,
    _migration_0005_outcomes,
    _migration_0006_security,
]


def _get_user_version(conn: Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _set_user_version(conn: Connection, version: int) -> None:
    # PRAGMA does not accept bound parameters; version is an int we control.
    conn.execute(f"PRAGMA user_version = {int(version)}")


def run_migrations() -> int:
    """Apply any pending migrations in order. Returns the resulting version.

    Idempotent: running it when already up to date does nothing. Each migration
    runs and the version is bumped within the same connection/transaction, so a
    failure rolls back cleanly and leaves the version unchanged.
    """
    _init_existing_stores()
    with get_connection() as conn:
        current = _get_user_version(conn)
        target = len(_MIGRATIONS)
        if current >= target:
            return current
        for version in range(current + 1, target + 1):
            migration = _MIGRATIONS[version - 1]
            logger.info("applying migration %d (%s)", version, migration.__name__)
            migration(conn)
            _set_user_version(conn, version)
        return target


def init_all() -> None:
    """Provision the entire database schema (existing + Phase 2 tables).

    Safe to call repeatedly and concurrently-ish (each call opens its own
    connection). This is the canonical entry point for ensuring the schema.
    """
    run_migrations()


def current_version() -> int:
    """Return the database's current schema version."""
    with get_connection() as conn:
        return _get_user_version(conn)
