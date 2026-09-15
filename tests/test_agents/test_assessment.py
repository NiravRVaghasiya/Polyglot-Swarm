"""Tests for the Assessment Agent (CEFR estimation)."""

from __future__ import annotations

import pytest

from src.agents import assessment
from src.agents.assessment import CEFRMetrics, estimate_cefr
from src.config import settings


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(settings, "profiles_dir", str(data_dir / "profiles"), raising=False)
    monkeypatch.setattr(settings, "db_path", str(data_dir / "polyglot.db"), raising=False)
    return data_dir


class TestVocabBands:
    @pytest.mark.parametrize(
        "words,expected",
        [
            (0, "A1"),
            (300, "A1"),
            (500, "A2"),
            (999, "A2"),
            (1500, "B1"),
            (3000, "B2"),
            (5000, "C1"),
            (9000, "C2"),
        ],
    )
    def test_vocab_band(self, words, expected):
        assert assessment._vocab_band(words) == expected


class TestLengthBands:
    @pytest.mark.parametrize(
        "avg,expected",
        [(4, "A1"), (10, "A2"), (20, "B1"), (30, "B2"), (50, "C1")],
    )
    def test_length_band(self, avg, expected):
        assert assessment._length_band(avg) == expected


class TestEstimate:
    def test_conservative_min_of_signals(self):
        # Big vocab (B2) but short sentences (A2) -> conservative A2.
        m = CEFRMetrics(unique_words_used=3000, grammar_error_rate=0.0, avg_response_length=10)
        assert estimate_cefr(m) == "A2"

    def test_high_error_rate_downgrades(self):
        # B1 by vocab+length, but frequent errors pull it to A2.
        m = CEFRMetrics(unique_words_used=1500, grammar_error_rate=0.6, avg_response_length=20)
        assert estimate_cefr(m) == "A2"

    def test_downgrade_floored_at_a1(self):
        m = CEFRMetrics(unique_words_used=100, grammar_error_rate=1.0, avg_response_length=5)
        assert estimate_cefr(m) == "A1"

    def test_no_signal_retains_current(self):
        m = CEFRMetrics(unique_words_used=0, grammar_error_rate=0.0, avg_response_length=0.0)
        assert estimate_cefr(m, current_level="B1") == "B1"

    def test_advanced_learner(self):
        m = CEFRMetrics(unique_words_used=5000, grammar_error_rate=0.0, avg_response_length=45)
        assert estimate_cefr(m) == "C1"


class TestComputeMetrics:
    def test_counts_user_turns_only(self, temp_storage):
        from src.memory import vocabulary_db

        vocabulary_db.upsert_word("u1", "Spanish", "mesa")
        state = {
            "user_id": "u1",
            "language": "Spanish",
            "messages": [
                {"role": "user", "content": "una dos tres cuatro"},
                {"role": "assistant", "content": "ignored ignored ignored ignored ignored"},
                {"role": "user", "content": "seis"},
            ],
            "grammar_errors": [{"rule": "x"}],
        }
        metrics = assessment.compute_metrics(state)
        assert metrics.unique_words_used == 1
        # (4 + 1) / 2 user turns = 2.5 avg
        assert metrics.avg_response_length == 2.5
        assert metrics.grammar_error_rate == 0.5


class TestAssessmentNode:
    async def test_persists_cefr_to_profile(self, temp_storage, monkeypatch):
        from src.memory import user_profile

        # Simulate a B1-sized vocabulary without a slow bulk insert.
        monkeypatch.setattr(assessment.vocabulary_db, "count_for_user", lambda u, lang: 1500)

        long_sentence = " ".join(["palabra"] * 20)
        state = {
            "user_id": "u1",
            "language": "Spanish",
            "cefr_level": "A2",
            "messages": [{"role": "user", "content": long_sentence}],
            "grammar_errors": [],
        }
        result = await assessment.assessment_node(state)
        assert result["cefr_level"] == "B1"

        # Persisted to the profile for next session.
        profile = user_profile.load_profile("u1")
        assert profile.cefr_for("Spanish") == "B1"
