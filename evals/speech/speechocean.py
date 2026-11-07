"""speechocean762 — an external, expert-labelled corpus (CC BY 4.0).

5,000 English read-aloud utterances by 250 Mandarin-L1 speakers, half
children and half adults. Five experts scored each utterance at sentence
level (accuracy, fluency, prosody, completeness), word level (accuracy,
stress) and phone level. Source: https://www.openslr.org/101/.

The corpus is downloaded to ``evals/speech/external/`` (git-ignored) and
not redistributed.

**Scope.** All learners are Mandarin-L1 speakers of English reading aloud.
Results here do **not** transfer to Spanish learners, to free speech, or to
other L1s.

**Splits.** The corpus's own train split is the *dev* set: it is used to fit
the fluency map and to decide the pronunciation-proxy gate. Its test split
is held out. Sampling is deterministic and stratified by speaker age group.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent / "external" / "speechocean762"
CHILD_MAX_AGE = 15


def available() -> bool:
    return (ROOT / "resource" / "scores.json").exists()


def _kv(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            k, v = line.split(maxsplit=1)
            out[k] = v.strip()
    return out


def utterances(split: str) -> list[dict[str, Any]]:
    """All utterances of a corpus split (``train`` or ``test``), with metadata."""
    base = ROOT / split
    text = _kv(base / "text")
    wavs = _kv(base / "wav.scp")
    utt2spk = _kv(base / "utt2spk")
    age = {k: int(v) for k, v in _kv(base / "spk2age").items()}
    gender = _kv(base / "spk2gender")
    scores = json.loads((ROOT / "resource" / "scores.json").read_text(encoding="utf-8"))
    out = []
    for utt, ref in sorted(text.items()):
        spk = utt2spk[utt]
        s = scores[utt]
        out.append(
            {
                "clip_id": f"so762-{utt}",
                "utt": utt,
                "split": split,
                "path": str(ROOT / wavs[utt]),
                "language": "English",
                "reference": ref,
                "speaker": spk,
                "age": age.get(spk),
                "age_group": "child" if age.get(spk, 99) <= CHILD_MAX_AGE else "adult",
                "gender": {"f": "female", "m": "male"}.get(gender.get(spk, "").lower(), "unknown"),
                "expert": {
                    "accuracy": s["accuracy"],
                    "fluency": s["fluency"],
                    "prosodic": s["prosodic"],
                    "completeness": s["completeness"],
                    "total": s["total"],
                    "words": [
                        {"text": w["text"], "accuracy": w["accuracy"], "stress": w["stress"]}
                        for w in s["words"]
                    ],
                },
            }
        )
    return out


def sample(split: str, n: int, *, seed: str = "speech-eval-v1") -> list[dict[str, Any]]:
    """Deterministic sample, balanced across age groups."""
    rows = utterances(split)

    def key(r: dict[str, Any]) -> str:
        return hashlib.sha256(f"{seed}:{r['utt']}".encode()).hexdigest()

    groups: dict[str, list[dict[str, Any]]] = {}
    for r in sorted(rows, key=key):
        groups.setdefault(r["age_group"], []).append(r)
    per = n // max(1, len(groups))
    picked = [r for g in sorted(groups) for r in groups[g][:per]]
    return sorted(picked, key=lambda r: r["utt"])
