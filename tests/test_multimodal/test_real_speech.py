"""Opt-in: the real recogniser on real speech (POLYGLOT_REAL_SPEECH=1).

Needs the ``voice`` extra (openai-whisper) and the speechocean762 corpus under
``evals/speech/external/``. Never runs in the offline CI job.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from evals.speech import speechocean
from src.multimodal import pipeline
from src.multimodal.contracts import Status
from src.multimodal.speaking import SpeakingTask
from src.multimodal.transcription import WhisperLocalProvider

pytestmark = [
    pytest.mark.real_model,
    pytest.mark.skipif(
        os.getenv("POLYGLOT_REAL_SPEECH") != "1", reason="set POLYGLOT_REAL_SPEECH=1"
    ),
]


@pytest.mark.skipif(not speechocean.available(), reason="speechocean762 not downloaded")
def test_real_utterance_end_to_end(temp_storage):
    clip = speechocean.sample("test", 2)[0]
    data = open(clip["path"], "rb").read()
    out = asyncio.run(
        pipeline.assess_speaking(
            data,
            user_id="real",
            language="English",
            task=SpeakingTask("read_aloud", clip["reference"]),
            provider=WhisperLocalProvider("base"),
        )
    )
    assert out.transcript is not None and out.transcript.words
    assert out.report.status in (Status.OK, Status.PARTIAL)
    assert all(w.start <= w.end for w in out.transcript.words)
    assert out.report.dimension("pronunciation").status in (Status.ABSTAINED, Status.OK)
