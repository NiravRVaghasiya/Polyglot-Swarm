"""Tests for delayed-retention scheduling (Gate C: the missing producer).

`due_measurements` converts an assignment's timestamp + a fixed offset into a
concrete "measure this learner now" work list, so delayed retention can be
measured by a scheduled job rather than only by hand. `assign_to_variant`
forces a chosen arm (used by the ablation runner).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.memory import experiments


class TestAssignToVariant:
    def test_forces_the_chosen_variant(self, temp_storage):
        experiments.create_experiment("exp", ["A", "B", "C"])
        assert experiments.assign_to_variant("exp", "u1", "C") == "C"
        assert experiments.get_assignment("exp", "u1") == "C"

    def test_is_idempotent_and_does_not_reassign(self, temp_storage):
        experiments.create_experiment("exp", ["A", "B"])
        experiments.assign_to_variant("exp", "u1", "A")
        # A second call with a different variant must NOT move the user.
        assert experiments.assign_to_variant("exp", "u1", "B") == "A"
        assert experiments.get_assignment("exp", "u1") == "A"


class TestDueMeasurements:
    def _assign_at(self, experiment, user_id, variant, when):
        """Assign a user, then backdate their assigned_at for deterministic tests."""
        from src.memory.db import get_connection

        experiments.create_experiment(experiment, [variant])
        experiments.assign_to_variant(experiment, user_id, variant)
        with get_connection() as conn:
            conn.execute(
                "UPDATE experiment_assignments SET assigned_at=? WHERE experiment=? AND user_id=?",
                (when.isoformat(), experiment, user_id),
            )

    def test_nothing_due_right_after_assignment(self, temp_storage):
        experiments.create_experiment("exp", ["A"])
        experiments.assign_to_variant("exp", "u1", "A")
        assert experiments.due_measurements("exp") == []

    def test_delayed_1d_due_after_a_day(self, temp_storage):
        base = datetime(2026, 1, 1, tzinfo=UTC)
        self._assign_at("exp", "u1", "A", base)

        due = experiments.due_measurements("exp", now=base + timedelta(days=1, hours=1))
        points = {d["measurement_point"] for d in due}
        assert "delayed_1d" in points
        assert "delayed_7d" not in points
        assert "delayed_30d" not in points

    def test_all_delayed_points_due_after_a_month(self, temp_storage):
        base = datetime(2026, 1, 1, tzinfo=UTC)
        self._assign_at("exp", "u1", "A", base)

        due = experiments.due_measurements("exp", now=base + timedelta(days=31))
        points = {d["measurement_point"] for d in due}
        assert points == {"delayed_1d", "delayed_7d", "delayed_30d"}

    def test_already_recorded_points_are_not_due_again(self, temp_storage):
        base = datetime(2026, 1, 1, tzinfo=UTC)
        self._assign_at("exp", "u1", "A", base)
        experiments.record_outcome("exp", "u1", "delayed_1d", "metric", 1.0, variant="A")

        due = experiments.due_measurements("exp", now=base + timedelta(days=2))
        points = {d["measurement_point"] for d in due}
        assert "delayed_1d" not in points  # already recorded

    def test_due_items_are_sorted_oldest_first(self, temp_storage):
        base = datetime(2026, 1, 1, tzinfo=UTC)
        self._assign_at("exp", "u1", "A", base)

        due = experiments.due_measurements("exp", now=base + timedelta(days=31))
        due_ats = [d["due_at"] for d in due]
        assert due_ats == sorted(due_ats)

    def test_multiple_learners_each_get_their_own_due_items(self, temp_storage):
        base = datetime(2026, 1, 1, tzinfo=UTC)
        self._assign_at("exp", "u1", "A", base)
        self._assign_at("exp", "u2", "A", base)

        due = experiments.due_measurements("exp", now=base + timedelta(days=8))
        users = {d["user_id"] for d in due}
        assert users == {"u1", "u2"}
        # delayed_1d + delayed_7d for each of 2 learners = 4 items.
        assert len(due) == 4


@pytest.mark.parametrize("point", ["delayed_1d", "delayed_7d", "delayed_30d"])
def test_delay_offsets_are_positive(point):
    from src.memory.experiments import _DELAY_OFFSET_SECONDS

    assert _DELAY_OFFSET_SECONDS[point] > 0
