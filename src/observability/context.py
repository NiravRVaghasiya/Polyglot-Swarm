"""Interaction context — the correlation id carried through a turn.

Handling a single learner turn fans out into many independent calls: memory
retrieval, one or more LLM calls (across agents), grammar analysis, the
evaluator, learner-state updates, and a curriculum decision. Each of those
already emits its own record (model runs, evidence events), but until now those
records shared no common key, so a turn could not be reconstructed end-to-end.

This module carries a single *interaction id* (and the owning *session id*)
through the turn using :class:`contextvars.ContextVar`. Because context vars
propagate across ``await`` boundaries and are copied into tasks, every call
made while a turn is being handled sees the same id — without threading it
through every function signature. Telemetry (:mod:`src.llm.telemetry` via
:mod:`src.llm.factory`) reads :func:`current_interaction` when it stamps a
model run, and :mod:`src.observability.trace` uses the id to stitch the records
back together.

The design deliberately avoids a new span store or an OpenTelemetry dependency:
it reuses the signals the system already persists (Phase 2 evidence + Phase 3
model runs) and only adds the missing correlation key.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

# The current interaction/session ids for the running turn. ``None`` means "no
# turn in scope" (e.g. a stray background call), in which case records are left
# uncorrelated rather than being force-fit into some interaction.
_interaction_id: ContextVar[str | None] = ContextVar("polyglot_interaction_id", default=None)
_session_id: ContextVar[str | None] = ContextVar("polyglot_session_id", default=None)


def new_interaction_id() -> str:
    """Return a fresh, opaque interaction id (uuid4 hex)."""
    return uuid.uuid4().hex


def current_interaction() -> str | None:
    """The interaction id for the turn in scope, or ``None`` if unset."""
    return _interaction_id.get()


def current_session() -> str | None:
    """The session id for the turn in scope, or ``None`` if unset."""
    return _session_id.get()


@contextmanager
def interaction_scope(
    *,
    session_id: str | None = None,
    interaction_id: str | None = None,
) -> Iterator[str]:
    """Bind an interaction (and its session) for the duration of a turn.

    Every model run recorded and every evidence event written while this scope
    is active is correlated by the yielded interaction id. If ``interaction_id``
    is not supplied a fresh one is generated, so callers can simply write::

        with interaction_scope(session_id=session_id) as iid:
            ...  # handle the turn; iid is the correlation key

    The previous ids are restored on exit (scopes nest safely).

    Args:
        session_id: The session this interaction belongs to. Left unchanged when
            ``None`` so an inner scope can inherit the outer session.
        interaction_id: Reuse an existing id (e.g. one supplied by a client);
            a new one is generated when ``None``.

    Yields:
        The active interaction id.
    """
    iid = interaction_id or new_interaction_id()
    interaction_token: Token[str | None] = _interaction_id.set(iid)
    session_token: Token[str | None] | None = None
    if session_id is not None:
        session_token = _session_id.set(session_id)
    try:
        yield iid
    finally:
        _interaction_id.reset(interaction_token)
        if session_token is not None:
            _session_id.reset(session_token)
