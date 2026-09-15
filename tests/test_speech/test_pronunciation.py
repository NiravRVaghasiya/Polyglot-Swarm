"""Tests for pronunciation feedback."""

from __future__ import annotations

from src.speech import pronunciation
from src.speech.pronunciation import assess_pronunciation, feedback_note


class TestAssess:
    def test_perfect_match(self):
        result = assess_pronunciation("una mesa para dos", "una mesa para dos")
        assert result["accuracy"] == 1.0
        assert result["problem_words"] == []
        assert all(w["ok"] for w in result["words"])

    def test_case_and_punctuation_insensitive(self):
        result = assess_pronunciation("Una mesa, por favor.", "una mesa por favor")
        assert result["accuracy"] == 1.0

    def test_flags_missed_word(self):
        # Learner dropped/mispronounced "restaurante" -> ASR heard something else.
        result = assess_pronunciation("quiero ir al restaurante", "quiero ir al rrrestorante")
        assert "restaurante" in result["problem_words"]
        assert result["accuracy"] < 1.0

    def test_near_miss_scores_higher_than_total_miss(self):
        near = assess_pronunciation("restaurante", "restorante")
        total = assess_pronunciation("restaurante", "xyz")
        near_sim = near["words"][0]["similarity"]
        total_sim = total["words"][0]["similarity"]
        assert near_sim > total_sim

    def test_missing_word_scored_zero(self):
        result = assess_pronunciation("hola buenos dias", "hola dias")
        buenos = next(w for w in result["words"] if w["target"] == "buenos")
        assert buenos["similarity"] == 0.0
        assert buenos["ok"] is False

    def test_empty_target(self):
        result = assess_pronunciation("", "anything")
        assert result["accuracy"] == 0.0
        assert result["words"] == []

    def test_extra_heard_words_ignored(self):
        # ASR heard extra words; target words still all matched.
        result = assess_pronunciation("hola", "hola hola hola")
        assert result["accuracy"] == 1.0


class TestFeedbackNote:
    def test_perfect_note(self):
        note = feedback_note("una mesa", "una mesa")
        assert note is not None
        assert "excellent" in note.lower()

    def test_problem_note_lists_words(self):
        note = pronunciation.feedback_note("quiero restaurante", "quiero xyz")
        assert note is not None
        assert "restaurante" in note

    def test_empty_target_no_note(self):
        assert feedback_note("", "hola") is None
