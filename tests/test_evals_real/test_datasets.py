"""Dataset validation: schema, versioning, checksums, splits, leakage, provenance."""

from __future__ import annotations

import pytest

from evals.real import datasets as ds
from evals.real.schema import GRAMMAR_CATEGORIES, Annotation, GrammarCase


class TestPublishedDatasets:
    @pytest.mark.parametrize("task", ds.TASKS)
    def test_published_files_match_source(self, task):
        # The committed split files are exactly what the source builds:
        # nobody edited a split by hand or forgot to rebuild.
        manifest, files = ds.render_dataset(task)
        published = ds.DATASETS_DIR / task / manifest.version
        for name, data in files.items():
            assert (published / name).read_bytes() == data, f"{task}/{name} is stale"
        assert ds.load_manifest(task, manifest.version) == manifest

    @pytest.mark.parametrize("task", ds.TASKS)
    def test_checksums_verify(self, task):
        for split in ("dev", "test"):
            manifest, cases = ds.load_split(task, split)
            assert cases
            assert manifest.counts[split] == len(cases)

    def test_tampered_file_is_refused(self, tmp_path, monkeypatch):
        manifest, files = ds.render_dataset("grammar")
        root = tmp_path / "datasets"
        out = root / "grammar" / manifest.version
        out.mkdir(parents=True)
        for name, data in files.items():
            (out / name).write_bytes(data)
        (out / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
        (out / "test.jsonl").write_bytes(files["test.jsonl"].replace(b"Yo soy", b"Yo estoy", 1))
        monkeypatch.setattr(ds, "DATASETS_DIR", root)
        ds.load_split("grammar", "dev")
        with pytest.raises(ds.DatasetIntegrityError):
            ds.load_split("grammar", "test")

    @pytest.mark.parametrize("task", ds.TASKS)
    def test_no_leakage(self, task):
        assert ds.leakage_report(task) == {
            "shared_groups": [],
            "shared_texts": [],
            "in_prompts": [],
        }

    def test_split_is_a_function_of_the_group(self):
        _, cases = ds.load_source("grammar")
        by_group: dict[str, set[str]] = {}
        for c in cases:
            by_group.setdefault(c.group_id, set()).add(c.split)
            assert c.split == ds.split_for_group(c.group_id)
        assert all(len(s) == 1 for s in by_group.values())

    def test_both_splits_have_error_and_clean_cases(self):
        for split in ("dev", "test"):
            _, cases = ds.load_split("grammar", split)
            labels = {c.has_error for c in cases}
            assert True in labels and False in labels

    def test_coverage_of_categories_and_languages(self):
        _, cases = ds.load_source("grammar")
        assert {c.category for c in cases} == set(GRAMMAR_CATEGORIES)
        assert len({c.language for c in cases}) >= 5
        assert {c.cefr_level for c in cases} >= {"A1", "A2", "B1", "B2", "C1"}
        assert {c.difficulty for c in cases} == {"easy", "medium", "hard"}

    def test_error_cases_carry_acceptable_alternatives(self):
        _, cases = ds.load_source("grammar")
        for c in cases:
            for e in c.expected_errors:
                assert e.corrections and e.constructions
                assert e.span in c.text

    def test_provenance_is_honest(self):
        # No case may claim expert validation: none has been done.
        for task in ds.TASKS:
            m = ds.load_manifest(task)
            assert set(m.validation_status_counts) == {"author_labeled"}
            assert "No qualified human expert" in m.provenance
            assert m.rubric_version and m.schema_version


def _case(**kw):
    base = dict(
        case_id="x",
        group_id="g",
        language="Spanish",
        text="Yo soy hambre.",
        category="incorrect",
        cefr_level="A1",
        difficulty="easy",
        has_error=True,
        expected_errors=[
            {"span": "soy hambre", "corrections": ["tengo hambre"], "constructions": ["x"]}
        ],
        annotations=[
            Annotation(
                annotator_id="a",
                annotator_type="author",
                has_error=True,
                rubric_version="r",
                annotated_at="2026-01-01",
            )
        ],
        validation_status="author_labeled",
    )
    base.update(kw)
    return GrammarCase(**base)


class TestSchemaRules:
    def test_valid_case(self):
        assert _case().has_error

    def test_span_must_be_in_text(self):
        with pytest.raises(ValueError):
            _case(expected_errors=[{"span": "nope", "corrections": ["a"], "constructions": ["b"]}])

    def test_error_case_needs_expected_errors(self):
        with pytest.raises(ValueError):
            _case(expected_errors=[])

    def test_ambiguous_has_no_label(self):
        with pytest.raises(ValueError):
            _case(category="ambiguous")

    def test_expert_status_needs_an_expert_annotation(self):
        with pytest.raises(ValueError):
            _case(validation_status="expert_validated")

    def test_context_case_needs_context(self):
        with pytest.raises(ValueError):
            _case(category="context_inappropriate")
