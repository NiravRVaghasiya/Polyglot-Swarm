"""End-to-end: finalize_session runs all agents and builds the full report."""

from __future__ import annotations

import pytest

from src.agents import transfer
from src.config import settings
from src.llm.provider import LLMProvider
from src.memory import analytics, user_profile, vocabulary_db
from src.orchestrator.lifecycle import (
    build_initial_state,
    build_session_report,
    finalize_session,
)


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(settings, "profiles_dir", str(data_dir / "profiles"), raising=False)
    monkeypatch.setattr(settings, "db_path", str(data_dir / "polyglot.db"), raising=False)
    monkeypatch.setattr(settings, "chroma_path", str(data_dir / "chroma"), raising=False)
    return data_dir


class TransferProvider(LLMProvider):
    name = "transfer"

    def is_available(self) -> bool:
        return True

    async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
        return (
            '{"transfers": [{"word": "restaurante", '
            '"cognates": {"Italian": "ristorante"}, "false_friends": []}]}'
        )


def _completed_state(temp_storage):
    user_profile.create_profile(
        "learner", target_languages=["Spanish", "Italian"],
        cefr_by_language={"Spanish": "A2"},
    )
    state = build_initial_state("learner", "Spanish")
    state["messages"] = [
        {"role": "user", "content": "Hola, quiero una mesa en el restaurante"},
        {"role": "assistant", "content": "¡Claro! Síganme."},
    ]
    state["new_vocabulary"] = [
        {"word": "restaurante", "translation": "restaurant", "pos": "noun",
         "context_sentence": "una mesa en el restaurante"},
    ]
    state["grammar_errors"] = [
        {"original": "quiero una mesa", "correction": "quisiera una mesa",
         "rule": "politeness", "explanation": "", "severity": "minor"},
    ]
    state["cultural_notes"] = ["In Spain, 'quisiera' is more polite than 'quiero'."]
    return state


class TestBuildReport:
    def test_report_has_all_sections(self, temp_storage):
        state = _completed_state(temp_storage)
        state["transfer_suggestions"] = [
            {"word": "restaurante", "cognates": {"Italian": "ristorante"}, "false_friends": []}
        ]
        report = build_session_report(state)
        assert "Grammar" in report
        assert "New vocabulary" in report
        assert "Cultural notes" in report
        assert "Level estimate" in report
        assert "Cross-language transfer" in report
        assert "ristorante" in report


class TestFinalizeSession:
    async def test_runs_all_agents_and_persists(self, temp_storage, monkeypatch):
        monkeypatch.setattr(transfer, "get_provider", lambda tier: TransferProvider())

        state = _completed_state(temp_storage)
        result = await finalize_session(state)

        report = result["report"]
        # All five sections present.
        for marker in ("Grammar", "New vocabulary", "Cultural notes",
                       "Level estimate", "Cross-language transfer"):
            assert marker in report
        # Transfer produced a cognate.
        assert "ristorante" in report

        # Persistence happened.
        assert result["persisted"]["vocabulary"] == 1
        assert result["persisted"]["grammar_errors"] == 1
        words = {w["word"] for w in vocabulary_db.get_all_for_user("learner", "Spanish")}
        assert "restaurante" in words
        # Grammar error recorded as a pattern.
        patterns = analytics.get_error_patterns("learner", "Spanish")
        assert any(p["error_type"] == "politeness" for p in patterns)

    async def test_cefr_persisted_to_profile(self, temp_storage, monkeypatch):
        monkeypatch.setattr(transfer, "get_provider", lambda tier: TransferProvider())
        # Force a vocabulary size that maps to B1.
        monkeypatch.setattr(
            "src.agents.assessment.vocabulary_db.count_for_user",
            lambda u, lang: 1500,
        )
        state = _completed_state(temp_storage)
        # Long user turn so response-length band is also >= B1; no errors so the
        # high-error-rate downgrade does not apply.
        state["messages"] = [{"role": "user", "content": " ".join(["palabra"] * 20)}]
        state["grammar_errors"] = []

        await finalize_session(state)
        assert user_profile.load_profile("learner").cefr_for("Spanish") == "B1"

    async def test_sets_end_flag(self, temp_storage, monkeypatch):
        monkeypatch.setattr(transfer, "get_provider", lambda tier: TransferProvider())
        state = _completed_state(temp_storage)
        await finalize_session(state)
        assert state["should_end_session"] is True
