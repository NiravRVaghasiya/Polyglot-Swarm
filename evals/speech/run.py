"""Run the real speech pipeline over evaluation audio and store raw outputs.

Each clip goes through the production stages (``ingest_audio`` →
``WhisperLocalProvider``). The raw result is appended to a JSONL file:

- the transcript, with word timing and probabilities;
- the quality report;
- the latency;
- any failure.

Scoring (``analysis.py``) runs offline over these files, so metrics can be
recomputed without re-running the recogniser. Runs resume: clips already in
the file are skipped.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from src.multimodal.audio import AudioValidationError, ingest_audio
from src.multimodal.transcription import WhisperLocalProvider, run_transcription

RESULTS = Path(__file__).parent / "results"


def run_clips(
    clips: Iterable[dict[str, Any]],
    out_path: Path,
    *,
    model: str = "base",
    progress_every: int = 25,
) -> int:
    """Transcribe clips (dicts with ``clip_id``, ``path``, ``language``, metadata)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done: set[str] = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["clip_id"])
    provider = WhisperLocalProvider(model)
    n = 0
    with out_path.open("a", encoding="utf-8") as f:
        for clip in clips:
            if clip["clip_id"] in done:
                continue
            record: dict[str, Any] = {k: v for k, v in clip.items() if k != "path"}
            t0 = time.perf_counter()
            try:
                data = Path(clip["path"]).read_bytes()
                ingested = ingest_audio(data, user_id="eval", language=clip.get("language"))
                record["quality"] = ingested.quality.as_dict()
                record["ingest_ms"] = (time.perf_counter() - t0) * 1000
                if "no_speech_detected" in ingested.quality.issues:
                    record["skipped"] = "no_speech_detected"
                else:
                    obs, step = run_transcription(
                        provider,
                        ingested.asset.asset_id,
                        ingested.wav_bytes(),
                        language=clip.get("language"),
                    )
                    record["step"] = step.as_dict()
                    if obs is not None:
                        record["transcript"] = obs.data["transcript"].as_dict()
            except AudioValidationError as exc:
                record["rejected"] = exc.code
            record["total_ms"] = (time.perf_counter() - t0) * 1000
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            n += 1
            if progress_every and n % progress_every == 0:
                print(f"  {out_path.name}: {n} clips", flush=True)
    return n


def load(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
