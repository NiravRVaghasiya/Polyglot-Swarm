"""Listening comprehension tasks and scoring (ADR-0034).

A listening task is an audio stimulus with questions. The learner answers by
choosing or typing, never by speaking. Scoring is therefore independent of:

- speech-to-text (no transcription is involved);
- the learner's speaking ability.

The stimulus audio is synthesised from the task's script, with its voice and
rate, by the existing TTS module. Scoring does not need the audio at all.

Each question has a ``kind``, and the kinds are recorded separately:

- ``recognition`` — identify what was said (choose the word or phrase you
  heard);
- ``comprehension`` — understand the meaning (multiple choice or true/false
  about content);
- ``recall`` — reproduce content from memory (short free-text answer).

Free-text answers are matched case- and accent-insensitively, with a small
typo tolerance. Recall tests *listening*, not spelling, so ``tambien`` for
``también`` is correct.

Tasks carry the CEFR level of the script, the voice (accent), the speech rate
and the speaker style. The task's difficulty is the script's CEFR difficulty,
adjusted for rate: ±0.05 for fast or slow speech.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from src.evidence.difficulty import cefr_to_difficulty
from src.multimodal.contracts import DimensionResult, Status

BANK_DIR = Path(__file__).parent / "listening_bank"
KINDS = ("recognition", "comprehension", "recall")
FREE_TEXT_THRESHOLD = 0.85


@dataclass(frozen=True)
class Question:
    question_id: str
    kind: str
    prompt: str
    options: tuple[str, ...] = ()
    answers: tuple[str, ...] = ()  # accepted answers (option text or free text)

    def public(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "kind": self.kind,
            "prompt": self.prompt,
            "options": list(self.options),
        }


@dataclass(frozen=True)
class ListeningTask:
    task_id: str
    language: str
    cefr: str
    script: str
    voice: str
    rate: str = "+0%"
    style: str = "monologue"
    accent: str = ""
    questions: tuple[Question, ...] = field(default_factory=tuple)

    @property
    def difficulty(self) -> float:
        base = cefr_to_difficulty(self.cefr) or 0.5
        pct = int(self.rate.replace("%", "") or 0)
        adjust = 0.05 if pct >= 15 else (-0.05 if pct <= -15 else 0.0)
        return max(0.0, min(1.0, base + adjust))

    def public(self) -> dict[str, Any]:
        """The task as served to a learner: no script, no answers."""
        return {
            "task_id": self.task_id,
            "language": self.language,
            "cefr": self.cefr,
            "voice": self.voice,
            "accent": self.accent,
            "rate": self.rate,
            "style": self.style,
            "difficulty": round(self.difficulty, 4),
            "questions": [q.public() for q in self.questions],
        }


def _load(path: Path) -> list[ListeningTask]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    tasks = []
    for t in data["tasks"]:
        questions = tuple(
            Question(
                question_id=q["id"],
                kind=q["kind"],
                prompt=q["prompt"],
                options=tuple(q.get("options", [])),
                answers=tuple(q["answers"]),
            )
            for q in t["questions"]
        )
        for q in questions:
            if q.kind not in KINDS:
                raise ValueError(f"{t['id']}/{q.question_id}: unknown kind {q.kind!r}")
            if q.options and not set(q.answers) <= set(q.options):
                raise ValueError(f"{t['id']}/{q.question_id}: answer not among options")
        tasks.append(
            ListeningTask(
                task_id=t["id"],
                language=data["language"],
                cefr=t["cefr"],
                script=t["script"],
                voice=t["voice"],
                rate=t.get("rate", "+0%"),
                style=t.get("style", "monologue"),
                accent=t.get("accent", ""),
                questions=questions,
            )
        )
    return tasks


@lru_cache(maxsize=1)
def task_bank() -> dict[str, ListeningTask]:
    tasks: dict[str, ListeningTask] = {}
    for path in sorted(BANK_DIR.glob("*.yaml")):
        for t in _load(path):
            if t.task_id in tasks:
                raise ValueError(f"duplicate listening task id {t.task_id}")
            tasks[t.task_id] = t
    return tasks


def tasks_for(language: str) -> list[ListeningTask]:
    key = language.strip().lower()
    return [t for t in task_bank().values() if t.language.lower() == key]


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.strip().lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join("".join(c if c.isalnum() or c.isspace() else " " for c in t).split())


def answer_correct(question: Question, answer: str | None) -> bool:
    if answer is None or not str(answer).strip():
        return False
    given = _norm(str(answer))
    if question.options:
        return given in {_norm(a) for a in question.answers}
    return any(
        given == _norm(a) or SequenceMatcher(None, given, _norm(a)).ratio() >= FREE_TEXT_THRESHOLD
        for a in question.answers
    )


@dataclass
class ListeningResult:
    task: ListeningTask
    per_question: list[dict[str, Any]]
    dimensions: list[DimensionResult]


def score_answers(task: ListeningTask, answers: dict[str, str | None]) -> ListeningResult:
    """Score a submission; unanswered questions count as not demonstrated."""
    per_question = []
    for q in task.questions:
        given = answers.get(q.question_id)
        per_question.append(
            {
                "question_id": q.question_id,
                "kind": q.kind,
                "answered": given is not None and str(given).strip() != "",
                "correct": answer_correct(q, given),
            }
        )
    dims = []
    for kind in KINDS:
        rows = [p for p in per_question if p["kind"] == kind]
        if not rows:
            continue
        answered = [p for p in rows if p["answered"]]
        if not answered:
            dims.append(
                DimensionResult(
                    f"listening_{kind}", Status.ABSTAINED, "response", reason="no answers given"
                )
            )
            continue
        value = sum(1 for p in rows if p["correct"]) / len(rows)
        dims.append(
            DimensionResult(
                f"listening_{kind}",
                Status.OK,
                "response",
                value=value,
                # Deterministic scoring of a closed answer is reliable; free
                # text slightly less so (typo tolerance can misjudge).
                confidence=0.9 if kind != "recall" else 0.8,
                measures={"questions": len(rows), "correct": sum(1 for p in rows if p["correct"])},
            )
        )
    return ListeningResult(task=task, per_question=per_question, dimensions=dims)
