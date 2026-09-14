"""Tests for the JSON user profile store."""

from __future__ import annotations

from src.memory.user_profile import (
    UserProfile,
    create_profile,
    default_profile,
    load_profile,
    profile_exists,
    save_profile,
    update_profile,
)


class TestDefaults:
    def test_missing_profile_returns_default(self, temp_storage):
        profile = load_profile("nobody")
        assert isinstance(profile, UserProfile)
        assert profile.user_id == "nobody"
        assert profile.native_language == "English"
        assert profile.cefr_for("Spanish") == "A2"

    def test_missing_profile_not_written(self, temp_storage):
        load_profile("ghost")
        assert profile_exists("ghost") is False

    def test_cefr_for_unknown_language_uses_default(self, temp_storage):
        profile = default_profile("u1")
        assert profile.cefr_for("Klingon", default="B1") == "B1"


class TestRoundTrip:
    def test_create_and_load(self, temp_storage):
        create_profile(
            "alice",
            native_language="Polish",
            target_languages=["Spanish", "Italian"],
            goals=["order food in Madrid"],
        )
        assert profile_exists("alice") is True

        loaded = load_profile("alice")
        assert loaded.native_language == "Polish"
        assert loaded.target_languages == ["Spanish", "Italian"]
        assert loaded.goals == ["order food in Madrid"]

    def test_update_persists(self, temp_storage):
        create_profile("bob")
        update_profile("bob", cefr_by_language={"Spanish": "B1"}, interests=["cooking"])

        loaded = load_profile("bob")
        assert loaded.cefr_for("Spanish") == "B1"
        assert loaded.interests == ["cooking"]

    def test_update_missing_creates(self, temp_storage):
        assert profile_exists("carol") is False
        update_profile("carol", goals=["pass B2 exam"])
        assert profile_exists("carol") is True
        assert load_profile("carol").goals == ["pass B2 exam"]

    def test_save_returns_profile(self, temp_storage):
        p = UserProfile(user_id="dave", interests=["music"])
        returned = save_profile(p)
        assert returned is p
        assert load_profile("dave").interests == ["music"]


class TestAtomicWrite:
    def test_no_temp_files_left_behind(self, temp_storage):
        create_profile("erin")
        profiles = list((temp_storage / "user_profiles").iterdir())
        # Only the final JSON file should remain — no .tmp leftovers.
        assert [p.name for p in profiles] == ["erin.json"]
