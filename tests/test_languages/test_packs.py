"""Phase 10 tests: the general language-pack loader across es/pl/it."""

from __future__ import annotations

import pytest

from src.languages import (
    collocations_for,
    frequency_rank,
    has_pack,
    list_constructions,
    load_pack,
    register_notes_for,
)
from src.languages.paths import pack_code, pack_dir


class TestPaths:
    def test_name_to_code(self):
        assert pack_code("Spanish") == "es"
        assert pack_code("Polish") == "pl"
        assert pack_code("Italian") == "it"

    def test_accepts_raw_code(self):
        assert pack_code("es") == "es"

    def test_unknown_language(self):
        assert pack_code("Klingon") is None
        assert pack_dir("Klingon") is None


class TestPackLoading:
    @pytest.mark.parametrize(
        "language,family",
        [("Spanish", "Romance"), ("Polish", "West Slavic"), ("Italian", "Romance")],
    )
    def test_all_three_packs_load(self, language, family):
        pack = load_pack(language)
        assert pack is not None
        assert pack.metadata.family == family
        assert pack.frequency  # has a frequency list
        assert pack.collocations  # has collocations

    def test_unknown_language_returns_none(self):
        assert load_pack("Klingon") is None

    def test_has_pack(self):
        assert has_pack("Spanish")
        assert not has_pack("Klingon")

    def test_metadata_fields(self):
        pack = load_pack("Polish")
        assert pack.metadata.code == "pl"
        assert "Slavic" in pack.metadata.family


class TestFrequency:
    def test_rank_is_one_based_and_ordered(self):
        # "que" is the first word in the Spanish frequency list.
        assert frequency_rank("Spanish", "que") == 1

    def test_rank_case_insensitive(self):
        assert frequency_rank("Spanish", "MESA") == frequency_rank("Spanish", "mesa")

    def test_unknown_word_none(self):
        assert frequency_rank("Spanish", "zzzznotaword") is None

    def test_unknown_language_none(self):
        assert frequency_rank("Klingon", "x") is None


class TestCollocations:
    def test_spanish_has_decision_collocation(self):
        phrases = {c.phrase for c in collocations_for("Spanish")}
        assert "tomar una decisión" in phrases

    def test_collocation_fields(self):
        colloc = collocations_for("Italian")
        assert colloc
        assert colloc[0].translation
        assert colloc[0].register_label  # alias populated

    def test_unknown_language_empty(self):
        assert collocations_for("Klingon") == []


class TestRegisterNotes:
    def test_spanish_register_notes(self):
        topics = {n.topic for n in register_notes_for("Spanish")}
        assert "tú vs usted" in topics

    def test_voseo_is_informal(self):
        voseo = [n for n in register_notes_for("Spanish") if n.topic == "voseo"]
        assert voseo and voseo[0].register_label == "informal"

    def test_unknown_language_empty(self):
        assert register_notes_for("Klingon") == []


class TestGrammarStillWorks:
    def test_grammar_taxonomy_intact(self):
        # The Phase 4 taxonomy loader must still work after the refactor.
        constructions = {c.construction for c in list_constructions("Spanish")}
        assert "ser_vs_estar" in constructions
