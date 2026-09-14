"""LangGraph checkpointer backed by SQLite.

The orchestrator checkpoints ``LearnerState`` after every node so a session
survives process restarts and disconnects. This module builds an async SQLite
checkpointer at ``settings.db_path`` (thread_id == session_id), replacing the
in-memory ``MemorySaver`` used during early scaffolding.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.config import settings


def _db_path() -> Path:
    path = Path(settings.db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


async def build_async_checkpointer() -> Any:
    """Build and set up an :class:`AsyncSqliteSaver` at ``settings.db_path``.

    The returned saver owns an ``aiosqlite`` connection and has had ``setup()``
    called to create its checkpoint tables. Callers are responsible for the
    connection's lifecycle in long-running apps.
    """
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    conn = await aiosqlite.connect(str(_db_path()))
    saver = AsyncSqliteSaver(conn)
    await saver.setup()
    return saver


def build_sync_checkpointer() -> Any:
    """Build and set up a synchronous :class:`SqliteSaver` at ``settings.db_path``."""
    import sqlite3

    from langgraph.checkpoint.sqlite import SqliteSaver

    conn = sqlite3.connect(str(_db_path()), check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver
