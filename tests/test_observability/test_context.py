"""Phase 17 tests: the interaction-id contextvar and its scope manager."""

from __future__ import annotations

import asyncio

from src.observability.context import (
    current_interaction,
    current_session,
    interaction_scope,
    new_interaction_id,
)


class TestNewInteractionId:
    def test_returns_a_string(self):
        assert isinstance(new_interaction_id(), str)

    def test_ids_are_unique(self):
        assert new_interaction_id() != new_interaction_id()


class TestUnscoped:
    def test_no_scope_means_none(self):
        assert current_interaction() is None
        assert current_session() is None


class TestInteractionScope:
    def test_generates_id_when_not_supplied(self):
        with interaction_scope(session_id="s1") as iid:
            assert iid
            assert current_interaction() == iid
            assert current_session() == "s1"
        # Restored after exit.
        assert current_interaction() is None
        assert current_session() is None

    def test_reuses_supplied_interaction_id(self):
        with interaction_scope(session_id="s1", interaction_id="fixed-id") as iid:
            assert iid == "fixed-id"
            assert current_interaction() == "fixed-id"

    def test_nested_scopes_restore_outer_values(self):
        with interaction_scope(session_id="outer-session") as outer_iid:
            with interaction_scope(session_id="inner-session") as inner_iid:
                assert inner_iid != outer_iid
                assert current_interaction() == inner_iid
                assert current_session() == "inner-session"
            # Back to the outer scope's values.
            assert current_interaction() == outer_iid
            assert current_session() == "outer-session"
        assert current_interaction() is None
        assert current_session() is None

    def test_inner_scope_without_session_inherits_outer_session(self):
        with interaction_scope(session_id="outer-session"):
            with interaction_scope() as inner_iid:
                assert current_interaction() == inner_iid
                # session_id was not overridden, so the outer one still applies.
                assert current_session() == "outer-session"

    def test_exception_inside_scope_still_restores(self):
        assert current_interaction() is None
        try:
            with interaction_scope(session_id="s1"):
                raise ValueError("boom")
        except ValueError:
            pass
        assert current_interaction() is None
        assert current_session() is None


class TestAsyncPropagation:
    async def test_contextvar_visible_across_await(self):
        async def read_after_await() -> str | None:
            await asyncio.sleep(0)
            return current_interaction()

        with interaction_scope(session_id="s1", interaction_id="abc"):
            seen = await read_after_await()
        assert seen == "abc"

    async def test_concurrent_tasks_do_not_leak_ids(self):
        # Each task's copied context should see only its own scope's id, even
        # when tasks run concurrently — proving turns from different sessions
        # never cross-contaminate telemetry.
        async def run(session_id: str) -> str | None:
            with interaction_scope(session_id=session_id) as iid:
                await asyncio.sleep(0)
                assert current_interaction() == iid
                return current_interaction()

        results = await asyncio.gather(run("s1"), run("s2"), run("s3"))
        assert len(set(results)) == 3
