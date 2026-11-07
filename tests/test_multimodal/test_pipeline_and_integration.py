"""Pipeline orchestration, evidence/LKM integration, listening, privacy and API."""

from __future__ import annotations

import asyncio
import base64
import logging
from datetime import UTC, datetime, timedelta

import pytest

from src.evidence import store as evidence_store
from src.learner.estimation import EvidenceMasteryEngine
from src.multimodal import pipeline, store
from src.multimodal.contracts import Status
from src.multimodal.listening import answer_correct, score_answers, task_bank, tasks_for
from src.multimodal.speaking import SpeakingTask
from tests.test_multimodal.conftest import make_transcript, scripted, silence, speech_like, wav

AUDIO = wav(speech_like(2.0))


def _run(stt, task=None, data=AUDIO, **kw):
    return asyncio.run(
        pipeline.assess_speaking(
            data,
            user_id=kw.pop("user_id", "u1"),
            language=kw.pop("language", "Spanish"),
            task=task or SpeakingTask("read_aloud", "quiero un café con leche por favor"),
            provider=stt,
            **kw,
        )
    )


class TestPipeline:
    def test_read_aloud_produces_separate_skill_evidence(self, temp_storage):
        out = _run(scripted(transcript=make_transcript("quiero un cafe con leche por favor")))
        r = out.report
        assert r.status == Status.PARTIAL  # fluency: measures only; pronunciation abstains
        dims = {d.dimension: d.status for d in r.dimensions}
        assert dims == {
            "fluency": Status.PARTIAL,
            "intelligibility": Status.OK,
            "pronunciation": Status.ABSTAINED,
        }
        by_skill = {(e.skill, e.subskill): e for e in out.events}
        intel = by_skill[("pronunciation", "intelligibility")]
        assert intel.assessment == "scored" and intel.payload["score"] == 1.0
        assert intel.modality == "audio" and intel.transcription_confidence == pytest.approx(0.9)
        assert intel.media_ref["asset_id"] == r.asset.asset_id and intel.observed is None
        # Measures without a validated score are exposure, not competence.
        assert by_skill[("speaking", "fluency")].assessment == "exposed"
        assert [s.stage for s in r.steps] == ["ingest", "transcribe", "assess"]

    def test_silence_abstains_without_calling_the_recogniser(self, temp_storage):
        stt = scripted(transcript=make_transcript("hallucinated text"))
        out = _run(stt, data=wav(silence(2.0)))
        assert out.report.status == Status.ABSTAINED and stt.calls == 0 and out.events == []

    def test_language_mismatch_abstains(self, temp_storage):
        stt = scripted(transcript=make_transcript("I want a coffee", language="en"))
        out = _run(stt)
        assert out.report.status == Status.ABSTAINED and "language_mismatch" in out.report.issues

    def test_recogniser_repetition_loop_abstains(self, temp_storage):
        # Seen on real speech: Whisper loops with high word probabilities.
        loop = "el mundo, " * 40
        out = _run(scripted(transcript=make_transcript(loop.strip(), prob=0.8)))
        assert out.report.status == Status.ABSTAINED and "repetition_loop" in out.report.issues
        assert out.events == []

    def test_unsupported_language_abstains(self, temp_storage):
        out = _run(scripted(transcript=make_transcript("x")), language="Klingon")
        assert out.report.status == Status.ABSTAINED

    def test_provider_failure_returns_partial_information(self, temp_storage):
        out = _run(scripted(fail="unavailable"))
        assert out.report.status == Status.FAILED and out.events == []
        assert out.report.quality["duration_s"] == 2.0  # ingestion results still returned
        assert out.report.steps[-1].error_category == "unavailable"

    def test_resubmitting_the_same_audio_does_not_double_count(self, temp_storage):
        stt = scripted(transcript=make_transcript("quiero un cafe con leche por favor"))
        _run(stt)
        _run(stt)
        rows = evidence_store.active_events("u1", "Spanish")
        est = EvidenceMasteryEngine().estimate_all(rows)["pronunciation"]
        assert est.graded_count == 2 and est.independent_count == 1

    def test_transcription_uncertainty_discounts_without_reading_as_weakness(self, temp_storage):
        sure = _run(
            scripted(transcript=make_transcript("quiero un cafe con leche por favor", prob=0.95)),
            user_id="a",
        )
        unsure = _run(
            scripted(transcript=make_transcript("quiero un cafe con leche por favor", prob=0.6)),
            user_id="b",
        )
        ea = EvidenceMasteryEngine().estimate_all(evidence_store.active_events("a", "Spanish"))
        eb = EvidenceMasteryEngine().estimate_all(evidence_store.active_events("b", "Spanish"))
        assert (
            sure.report.dimension("intelligibility").value
            == unsure.report.dimension("intelligibility").value
        )
        # Same learner performance; the uncertain recording simply counts for less.
        assert eb["pronunciation"].effective_n < ea["pronunciation"].effective_n
        assert eb["pronunciation"].mastery < ea["pronunciation"].mastery  # pulled toward the prior
        assert eb["pronunciation"].mastery > 0.5

    def test_spoken_grammar_abstains_on_read_aloud_and_low_confidence(self, temp_storage):
        out = _run(scripted(transcript=make_transcript("quiero un cafe")), analyze_grammar=True)
        assert out.report.dimension("spoken_grammar").status == Status.ABSTAINED
        free = SpeakingTask("free_speech")
        out = _run(
            scripted(transcript=make_transcript("yo soy hambre ahora mismo", prob=0.5)),
            task=free,
            analyze_grammar=True,
        )
        assert "confidence" in out.report.dimension("spoken_grammar").reason

    def test_no_audio_or_transcript_in_logs(self, temp_storage, caplog):
        caplog.set_level(logging.DEBUG, logger="polyglot")
        _run(scripted(transcript=make_transcript("secreto personal muy privado")))
        assert "secreto" not in caplog.text and "RIFF" not in caplog.text


class TestListening:
    def test_bank_is_valid_and_public_view_hides_answers(self):
        tasks = tasks_for("Spanish")
        assert len(tasks) >= 8 and {t.cefr for t in tasks} >= {"A1", "A2", "B1", "B2"}
        assert len({t.accent for t in tasks}) >= 4 and len({t.rate for t in tasks}) >= 3
        public = tasks[0].public()
        assert "script" not in public and all("answers" not in q for q in public["questions"])

    def test_free_text_is_accent_case_and_typo_tolerant(self):
        q = task_bank()["es-l-a2-fin-de-semana"].questions[2]
        assert answer_correct(q, "Pescado") and answer_correct(q, "pescdo")
        assert not answer_correct(q, "pollo") and not answer_correct(q, "")

    def test_scores_kinds_separately_and_records_per_question_evidence(self, temp_storage):
        task = task_bank()["es-l-a1-cafe"]
        report, events = pipeline.assess_listening(
            task, {"q1": "un vaso de agua", "q2": "dos euros", "q3": None}, user_id="u1"
        )
        dims = {d.dimension: d for d in report.dimensions}
        assert dims["listening_recognition"].value == 1.0
        assert dims["listening_comprehension"].value == 0.0
        assert dims["listening_recall"].status == Status.ABSTAINED
        assert {e.subskill for e in events} == {"recognition", "comprehension"}
        assert all(e.skill == "listening" and e.transcription_confidence is None for e in events)

    def test_scoring_needs_no_audio_or_recogniser(self):
        task = task_bank()["es-l-b1-trabajo"]
        result = score_answers(
            task, {"q1": "el jueves", "q2": "avisar antes del miércoles", "q3": "a las 10"}
        )
        assert all(p["correct"] for p in result.per_question)


class TestPrivacy:
    def test_audio_is_not_retained_by_default(self, temp_storage):
        out = _run(scripted(transcript=make_transcript("quiero un cafe")))
        row = store.get_submission("u1", out.report.submission_id)
        assert row is not None and row["retained"] is False and "storage_path" not in row
        assert not (temp_storage / "media").exists()

    def test_consented_retention_expires_and_is_purged(self, temp_storage):
        out = _run(scripted(transcript=make_transcript("quiero un cafe")), retain_audio=True)
        files = list((temp_storage / "media").rglob("*.wav"))
        assert len(files) == 1
        assert store.purge_expired(datetime.now(UTC) + timedelta(days=31)) == 1
        assert not files[0].exists()
        assert store.get_submission("u1", out.report.submission_id)["retained"] is False

    def test_access_is_scoped_and_deletion_removes_artifacts(self, temp_storage):
        out = _run(scripted(transcript=make_transcript("quiero un cafe")), retain_audio=True)
        sid = out.report.submission_id
        assert store.get_submission("someone-else", sid) is None
        assert not store.delete_submission("someone-else", sid)
        assert store.delete_submission("u1", sid)
        assert store.get_submission("u1", sid) is None
        assert not list((temp_storage / "media").rglob("*.wav"))

    def test_account_deletion_covers_submissions(self, temp_storage):
        _run(scripted(transcript=make_transcript("quiero un cafe")), retain_audio=True)
        from src.memory.privacy import delete_user_data, export_user_data

        assert len(export_user_data("u1")["media_submissions"]) == 1
        assert delete_user_data("u1")["media_submissions"] == 1
        assert store.list_submissions("u1") == []


class TestApi:
    def test_speaking_endpoint(self, auth_client, monkeypatch):
        client, headers, _ = auth_client
        monkeypatch.setattr(
            pipeline, "default_provider", lambda: scripted(transcript=make_transcript("hola amigo"))
        )
        body = {
            "audio_base64": base64.b64encode(AUDIO).decode(),
            "audio_format": "wav",
            "task_type": "read_aloud",
            "target_text": "hola amigo",
        }
        r = client.post("/api/v1/assessment/speaking", json=body, headers=headers)
        assert r.status_code == 200, r.text
        report = r.json()
        assert report["dimension" if False else "dimensions"][1]["value"] == 1.0
        listed = client.get("/api/v1/assessment/submissions", headers=headers).json()
        assert listed["submissions"][0]["submission_id"] == report["submission_id"]
        assert (
            client.delete(
                f"/api/v1/assessment/submissions/{report['submission_id']}", headers=headers
            ).status_code
            == 200
        )

    @pytest.mark.parametrize(
        ("body", "status", "code"),
        [
            ({"audio_base64": "!!!"}, 400, "invalid_base64"),
            (
                {"audio_base64": base64.b64encode(b"hello world, not audio").decode()},
                415,
                "unsupported_format",
            ),
        ],
    )
    def test_speaking_validation_errors(self, auth_client, body, status, code):
        client, headers, _ = auth_client
        r = client.post("/api/v1/assessment/speaking", json=body, headers=headers)
        assert r.status_code == status and r.json()["detail"]["code"] == code

    def test_listening_endpoints(self, auth_client):
        client, headers, user_id = auth_client
        tasks = client.get(
            "/api/v1/assessment/listening/tasks?language=Spanish", headers=headers
        ).json()["tasks"]
        tid = tasks[0]["task_id"]
        r = client.post(
            f"/api/v1/assessment/listening/tasks/{tid}/answers",
            json={"answers": {"q1": "un vaso de agua"}},
            headers=headers,
        )
        assert r.status_code == 200 and r.json()["evidence_ids"]
        bad = client.post(
            f"/api/v1/assessment/listening/tasks/{tid}/answers",
            json={"answers": {"nope": "x"}},
            headers=headers,
        )
        assert bad.status_code == 422
        assert (
            client.post(
                "/api/v1/assessment/listening/tasks/missing/answers",
                json={"answers": {}},
                headers=headers,
            ).status_code
            == 404
        )

    def test_requires_auth(self, client):
        assert client.get("/api/v1/assessment/submissions").status_code == 401
