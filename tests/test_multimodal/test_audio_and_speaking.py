"""Audio ingestion, quality analysis, transcription stage and speaking assessors."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.multimodal.audio import (
    AudioLimits,
    AudioValidationError,
    analyze_pcm16,
    ingest_audio,
    sniff_format,
)
from src.multimodal.contracts import Status
from src.multimodal.speaking import (
    FLUENCY_MAP,
    PRONUNCIATION_VALIDATED,
    VALIDATED_CONFIDENCE,
    SpeakingTask,
    align_target,
    assess_fluency,
    assess_intelligibility,
    assess_pronunciation,
    fluency_measures,
)
from src.multimodal.transcription import run_transcription
from src.speech.vad import has_speech
from tests.test_multimodal.conftest import (
    make_transcript,
    scripted,
    silence,
    speech_like,
    wav,
)


class TestIngestion:
    def test_valid_wav_is_accepted_with_quality_report(self):
        result = ingest_audio(wav(speech_like(2.0)), user_id="u", declared_format="wav")
        assert result.asset.media_format == "wav" and result.asset.duration_s == 2.0
        assert result.quality.issues == []
        assert result.quality.speech_ratio > 0.3 and result.quality.voiced_regions

    @pytest.mark.parametrize(
        ("data", "kw", "code"),
        [
            (b"", {}, "empty"),
            (b"not audio at all, just text", {}, "unsupported_format"),
            (wav(speech_like(0.1)), {}, "too_short"),
            (wav(speech_like(2.0)), {"declared_format": "mp3"}, "format_mismatch"),
        ],
    )
    def test_invalid_input_is_rejected_with_a_code(self, data, kw, code):
        with pytest.raises(AudioValidationError) as err:
            ingest_audio(data, user_id="u", **kw)
        assert err.value.code == code

    def test_size_and_duration_limits(self):
        data = wav(speech_like(3.0))
        with pytest.raises(AudioValidationError) as err:
            ingest_audio(data, user_id="u", limits=AudioLimits(max_bytes=1000))
        assert err.value.code == "too_large" and err.value.http_status == 413
        with pytest.raises(AudioValidationError) as err:
            ingest_audio(data, user_id="u", limits=AudioLimits(max_duration_s=1.0))
        assert err.value.code == "too_long"

    def test_silence_noise_and_clipping_are_flagged_not_rejected(self):
        assert "no_speech_detected" in analyze_pcm16(_pcm(silence(2.0))).issues
        noisy = analyze_pcm16(_pcm(speech_like(2.0, noise=6000)))
        assert "noisy" in noisy.issues
        clipped = analyze_pcm16(_pcm(speech_like(2.0, amp=60000)))
        assert "clipped" in clipped.issues

    def test_sniffing(self):
        assert sniff_format(b"OggS" + b"\0" * 20) == "ogg"
        assert sniff_format(b"\x1a\x45\xdf\xa3" + b"\0" * 20) == "webm"
        assert sniff_format(b"ID3" + b"\0" * 20) == "mp3"
        assert sniff_format(b"\0\0\0\x18ftypmp42" + b"\0" * 8) == "mp4"

    @pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
    @pytest.mark.parametrize(
        ("fmt", "args"), [("ogg", ["-c:a", "libopus"]), ("flac", []), ("mp3", [])]
    )
    def test_compressed_formats_decode_via_ffmpeg(self, fmt, args, tmp_path):
        src = tmp_path / "in.wav"
        # 2 s at 44.1 kHz (the helper generates at 16 kHz, so scale the length).
        src.write_bytes(wav(speech_like(2.0 * 44_100 / 16_000), sr=44_100))
        out = tmp_path / f"out.{fmt}"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), *args, str(out)], check=True
        )
        result = ingest_audio(out.read_bytes(), user_id="u", declared_format=fmt)
        assert result.asset.media_format == fmt
        assert 1.9 <= result.quality.duration_s <= 2.2

    def test_resampled_stereo_wav_needs_and_uses_the_decoder(self):
        if shutil.which("ffmpeg") is None:
            with pytest.raises(AudioValidationError) as err:
                ingest_audio(wav(speech_like(1.0), sr=44_100), user_id="u")
            assert err.value.code == "decoder_unavailable"
        else:
            result = ingest_audio(wav(speech_like(1.0), sr=44_100), user_id="u")
            assert result.asset.sample_rate == 16_000

    def test_vad_works_without_audioop(self):
        assert has_speech(_pcm(speech_like(1.0)))
        assert not has_speech(_pcm(silence(1.0, noise=5)))


def _pcm(samples: list[int]) -> bytes:
    return b"".join(
        int(max(-32768, min(32767, s))).to_bytes(2, "little", signed=True) for s in samples
    )


class TestTranscriptionStage:
    def test_success_records_provenance(self):
        obs, step = run_transcription(
            scripted(transcript=make_transcript("hola que tal")), "a1", b"x", language="Spanish"
        )
        assert obs is not None and step.status == Status.OK and step.provider == "scripted"
        assert obs.processing_confidence == pytest.approx(0.9)

    def test_transient_error_is_retried(self):
        stt = scripted(transcript=make_transcript("hola"), fail="error", fail_times=1)
        obs, step = run_transcription(stt, "a1", b"x", language="Spanish")
        assert obs is not None and step.attempts == 2

    @pytest.mark.parametrize("category", ["unavailable", "unsupported_language"])
    def test_permanent_errors_are_not_retried_and_never_raise(self, category):
        stt = scripted(fail=category)
        obs, step = run_transcription(stt, "a1", b"x", language="Spanish")
        assert obs is None and step.status == Status.FAILED
        assert step.error_category == category and stt.calls == 1

    def test_unavailable_provider_is_failed_not_substituted(self):
        obs, step = run_transcription(scripted(available=False), "a1", b"x", language=None)
        assert obs is None and step.error_category == "unavailable"


class TestSpeaking:
    def test_fluency_measures_come_from_timing(self):
        t = make_transcript("yo yo quiero un café con leche por favor", gaps=[0.05, 1.2, 0.05, 0.4])
        m = fluency_measures(t.words)
        assert m["repetitions"] >= 1 and m["pause_count"] == 2 and m["long_pauses"] == 1
        assert m["mean_length_of_run"] == pytest.approx(9 / 3)
        assert m["speech_rate_wpm"] > 0

    def test_fluency_without_a_validated_map_reports_measures_only(self):
        t = make_transcript("quiero un café con leche por favor")
        dim = assess_fluency(t, language_code="es", quality_issues=[], task_type="read_aloud")
        assert dim.status == Status.PARTIAL and dim.value is None and dim.measures
        assert "English read-aloud only" in dim.reason

    def test_fluency_is_scored_only_in_the_validated_scope(self):
        t = make_transcript("I would like a cup of coffee please", language="en")
        scored = assess_fluency(t, language_code="en", quality_issues=[], task_type="read_aloud")
        assert scored.status == Status.OK and 0.0 < scored.value < 1.0
        free = assess_fluency(t, language_code="en", quality_issues=[], task_type="free_speech")
        assert free.status == Status.PARTIAL and free.value is None

    def test_judgment_confidence_excludes_transcription_confidence(self):
        # Transcription confidence travels separately on the evidence event;
        # folding it in here too would count it twice.
        args = {"language_code": "en", "quality_issues": [], "task_type": "read_aloud"}
        sure = assess_fluency(make_transcript("a b c d e f g", prob=0.95), **args)
        unsure = assess_fluency(make_transcript("a b c d e f g", prob=0.6), **args)
        assert sure.confidence == unsure.confidence == VALIDATED_CONFIDENCE

    def test_shipped_fluency_map_is_the_benchmarked_one(self):
        path = Path("evals/speech/results/speech-benchmark.json")
        if not path.exists():
            pytest.skip("benchmark results not present")
        so = json.loads(path.read_text(encoding="utf-8"))["speechocean762"]
        fitted = so["fluency_map"]
        assert FLUENCY_MAP["fitted_on"] == fitted["fitted_on"]
        assert FLUENCY_MAP["intercept"] == pytest.approx(fitted["intercept"], abs=1e-5)
        for name, spec in fitted["features"].items():
            for key in ("mean", "sd", "coef"):
                assert FLUENCY_MAP["features"][name][key] == pytest.approx(spec[key], abs=1e-6)
        # The pronunciation proxy may only be enabled if it passed on dev and test.
        pp = so["pronunciation_proxy"]
        assert ("en" in PRONUNCIATION_VALIDATED) == (
            pp["passes_gate_on_dev"] and pp["passes_gate_on_test"]
        )

    @pytest.mark.parametrize(
        ("text", "prob", "issues", "reason"),
        [
            ("hola", 0.9, [], "fewer than"),
            ("quiero un café con leche", 0.3, [], "confidence"),
            ("quiero un café con leche", 0.9, ["no_speech_detected"], "no speech"),
        ],
    )
    def test_fluency_abstains(self, text, prob, issues, reason):
        dim = assess_fluency(
            make_transcript(text, prob=prob), language_code="es", quality_issues=issues
        )
        assert dim.status == Status.ABSTAINED and reason in dim.reason

    def test_intelligibility_does_not_penalise_accent_marks_or_case(self):
        t = make_transcript("Quiero un CAFE con leche")
        dim = assess_intelligibility(
            t, SpeakingTask("read_aloud", "quiero un café con leche"), quality_issues=[]
        )
        assert dim.status == Status.OK and dim.value == 1.0 and dim.feedback == []

    def test_unrecognised_words_get_no_word_level_correction(self):
        # Most words the recogniser misses were acceptable to experts, so the
        # feedback is one neutral note, never "you mispronounced X".
        t = make_transcript("quiero un cafe con lecho")
        dim = assess_intelligibility(
            t, SpeakingTask("read_aloud", "quiero un café con leche"), quality_issues=[]
        )
        assert dim.value == pytest.approx(0.8)
        (fb,) = dim.feedback
        assert fb["type"] == "recogniser_note" and "word" not in fb
        assert "4 of 5" in fb["message"] and "not a pronunciation error" in fb["message"]

    @pytest.mark.parametrize(
        ("task", "issues", "prob"),
        [
            (SpeakingTask("free_speech"), [], 0.9),
            (SpeakingTask("read_aloud", "hola amigo"), ["noisy"], 0.9),
            (SpeakingTask("read_aloud", "hola amigo"), [], 0.2),
        ],
    )
    def test_intelligibility_abstains(self, task, issues, prob):
        dim = assess_intelligibility(
            make_transcript("hola amiga", prob=prob), task, quality_issues=issues
        )
        assert dim.status == Status.ABSTAINED

    def test_pronunciation_abstains_without_validation(self):
        dim = assess_pronunciation(
            make_transcript("hola"), SpeakingTask("read_aloud", "hola"), language_code="es"
        )
        assert dim.status == Status.ABSTAINED and "validated" in dim.reason

    def test_alignment_handles_omissions(self):
        a = align_target("el gato negro duerme", make_transcript("el gato duerme").words)
        assert [x["recognised"] for x in a] == [True, True, False, True]
