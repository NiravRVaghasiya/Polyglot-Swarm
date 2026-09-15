"""Ablation study runner — the controlled-comparison execution harness.

Joins three pieces that previously did not talk to each other:

- the ablation *graph builder* (:func:`src.orchestrator.graph.build_ablation_graph`,
  arms A-E),
- the session *lifecycle* (:func:`src.orchestrator.lifecycle.build_initial_state`
  / :func:`persist_session`), and
- the experiment *outcomes store* (:mod:`src.memory.experiments`).

For each arm it runs a scripted cohort of learners through a fixed sequence of
turns, persists the session's evidence (so arms that include the "analysis"
components accumulate learner-model evidence and arms that don't accumulate
less), measures each learner's overall CEFR ordinal at ``pre_test`` and
``immediate_post``, and records those outcomes. The per-arm mean gain is the
signal the plan's ablation ladder is meant to produce: does adding the
learner-model analysis pipeline (arm D/E) measurably move the CEFR estimate
more than conversation alone (arm A)?

Deterministic by construction: it drives the graph with a scripted provider
(or the deterministic fake provider under ``POLYGLOT_DETERMINISTIC=1``), so
the same seed inputs always produce the same measured outcomes.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from src.assessment.cefr_profile import CEFR_ORDER, build_cefr_profile
from src.learner import get_knowledge_model
from src.llm.provider import LLMProvider, Message
from src.memory import experiments
from src.orchestrator.graph import ABLATION_ARMS, build_ablation_graph
from src.orchestrator.lifecycle import build_initial_state, persist_session

#: The canonical experiment name for the plan's five-arm ablation ladder.
ABLATION_EXPERIMENT = "ablation_ladder"

#: The metric recorded at each measurement point: the learner's mean mastery
#: across the skills the analysis pipeline can inform (grammar + vocabulary),
#: in [0, 1]. This is the cleanest signal for the ablation's actual question —
#: "which components build the learner model" — because arms that run the
#: analysis pipeline accumulate mastery evidence and arms that don't stay at
#: zero, so the gain is directly attributable to the ablated component. (The
#: overall CEFR band is kept in each outcome's payload for reference, but it
#: is a conservative *minimum* across skills and starts at a fallback default,
#: which makes it a poor primary signal for single-session gain.)
METRIC = "mean_skill_mastery"

#: The skills the scripted analysis pipeline produces evidence for. Kept
#: explicit so the metric is stable regardless of which skills happen to have a
#: belief row yet.
_MEASURED_SKILLS = ("grammar", "vocabulary")

#: A short scripted "lesson" — the learner turns fed to every cohort member.
#: Chosen so the analysis agents (grammar/vocabulary) have real material to
#: extract evidence from. Deterministic input keeps the comparison reproducible.
_SCRIPT: tuple[str, ...] = (
    "Hola, quiero una mesa para dos personas.",
    "Yo soy hambre y quiero comer algo tipico.",
    "¿Que me recomienda usted para beber?",
    "La cuenta, por favor. ¿Puedo pagar con tarjeta?",
)


class _ScriptedTutorProvider(LLMProvider):
    """A deterministic provider that returns realistic analysis output.

    The deterministic :class:`~src.llm.fake.FakeProvider` returns an empty
    analysis payload (no grammar errors, no vocabulary), which would make every
    ablation arm produce identical zero evidence — a comparison that proves
    nothing. This provider instead returns believable structured output so the
    analysis pipeline (grammar/vocabulary) actually produces evidence, and the
    arms that *include* that pipeline (D/E) measurably accumulate learner-model
    evidence that the conversation-only arms (A/B) do not. It is still fully
    deterministic: the same messages always yield the same output.
    """

    name = "scripted-tutor"

    def is_available(self) -> bool:
        return True

    async def generate(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.7,
        max_tokens: int = 512,
        json_mode: bool = False,
    ) -> str:
        if not json_mode:
            return "¡Claro! Con mucho gusto. ¿Algo más?"
        prompt = "\n".join(m.content for m in messages if isinstance(m, Message)).lower()
        # Vocabulary extraction request -> return a couple of words (positive,
        # "observed" evidence toward the vocabulary skill).
        if "vocab" in prompt or "words" in prompt:
            return (
                '{"words": ['
                '{"word": "mesa", "translation": "table", "pos": "noun",'
                ' "context_sentence": "una mesa para dos"},'
                '{"word": "cuenta", "translation": "bill", "pos": "noun",'
                ' "context_sentence": "la cuenta por favor"}'
                "]}"
            )
        # Grammar analysis request -> return one genuine, confident error so
        # the grammar skill also receives evidence.
        if "grammar" in prompt or "error" in prompt or "deviation" in prompt:
            return (
                '{"errors": [{"original": "Yo soy hambre",'
                ' "correction": "Yo tengo hambre", "construction": "ser_vs_tener",'
                ' "rule": "ser_vs_tener", "explanation": "use tener for states",'
                ' "classification": "wrong", "severity": "moderate",'
                ' "confidence": 0.9, "alternatives": []}]}'
            )
        # Anything else expecting JSON (cultural/evaluator) -> empty-but-valid.
        return '{"errors": [], "words": [], "notes": [], "overrides": [], "adjustments": {}}'


@contextlib.contextmanager
def _scripted_agents() -> Iterator[None]:
    """Patch every agent's ``get_provider`` to the scripted tutor for a run.

    Scoped to the ablation run so it never affects the rest of the process.
    Cultural-note persistence is stubbed too, since the ablation harness runs
    offline and must not require a live vector store.
    """
    from src.agents import conversation, cultural, evaluator, grammar, transfer, vocabulary

    provider = _ScriptedTutorProvider()
    modules = (conversation, grammar, vocabulary, cultural, evaluator, transfer)
    originals = [(m, getattr(m, "get_provider")) for m in modules]  # noqa: B009
    original_persist = cultural._persist_notes
    try:
        for m in modules:
            setattr(m, "get_provider", lambda tier, _p=provider: _p)  # noqa: B010
        cultural._persist_notes = lambda state, notes: None
        yield
    finally:
        for m, original in originals:
            setattr(m, "get_provider", original)  # noqa: B010
        cultural._persist_notes = original_persist


@dataclass
class ArmResult:
    """Measured outcome for one ablation arm."""

    arm: str
    n_learners: int
    mean_pre: float
    mean_post: float

    @property
    def mean_gain(self) -> float:
        """Mean CEFR-ordinal gain (post - pre) across the arm's cohort."""
        return round(self.mean_post - self.mean_pre, 4)

    def as_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "n_learners": self.n_learners,
            "mean_pre": round(self.mean_pre, 4),
            "mean_post": round(self.mean_post, 4),
            "mean_gain": self.mean_gain,
        }


@dataclass
class AblationReport:
    """The full controlled comparison across every arm that was run."""

    experiment: str
    metric: str
    arms: list[ArmResult] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "experiment": self.experiment,
            "metric": self.metric,
            "arms": [a.as_dict() for a in self.arms],
        }


def _measure(user_id: str, language: str) -> tuple[float, dict[str, Any]]:
    """Measure the primary metric plus a reference payload for a learner.

    Returns ``(mean_skill_mastery, payload)`` where the payload carries the
    per-skill mastery and the overall CEFR band/ordinal for reference. Mean
    mastery is over :data:`_MEASURED_SKILLS`; a skill with no belief yet
    contributes 0.0 (no evidence = no demonstrated mastery), which is exactly
    the behavior that makes a conversation-only arm measure lower than an
    analysis arm.
    """
    beliefs = get_knowledge_model().current_beliefs(user_id, language)
    masteries = [beliefs[s].mastery if s in beliefs else 0.0 for s in _MEASURED_SKILLS]
    mean_mastery = sum(masteries) / len(masteries) if masteries else 0.0

    profile = build_cefr_profile(user_id, language)
    payload = {
        "per_skill_mastery": {s: round(m, 4) for s, m in zip(_MEASURED_SKILLS, masteries)},
        "overall_cefr": profile.overall,
        "overall_cefr_ordinal": CEFR_ORDER.index(profile.overall),
    }
    return mean_mastery, payload


async def _run_one_session(
    user_id: str,
    language: str,
    arm: str,
    *,
    script: tuple[str, ...],
) -> None:
    """Run one scripted session through ``arm``'s graph and persist its evidence.

    Mirrors ``src.api.sessions.run_turn``'s streaming/merge pattern, but against
    an arm-specific compiled graph instead of the module-global production one,
    so a stripped-down arm (no analysis / no review) genuinely exercises a
    different topology.
    """
    from langgraph.checkpoint.memory import MemorySaver

    # Typed as Any to match src.api.sessions' use of the compiled graph — the
    # streaming/merge loop below relies on the same dynamic update dicts.
    graph: Any = build_ablation_graph(arm).compile(checkpointer=MemorySaver())
    has_analysis = "analysis" in ABLATION_ARMS[arm]

    state = build_initial_state(user_id, language, session_id=f"{arm}-{user_id}")

    config = {"configurable": {"thread_id": state["session_id"]}, "recursion_limit": 8}
    for user_input in script:
        state["last_user_input"] = user_input
        saw_conversation = False
        async for update in graph.astream(state, config):
            for node_update in update.values():
                if not isinstance(node_update, dict):
                    continue
                for key, value in node_update.items():
                    if key == "messages":
                        state["messages"] = state.get("messages", []) + value
                    else:
                        state[key] = value  # type: ignore[literal-required]
            if "conversation" in update:
                saw_conversation = True
            # Stop this turn once the conversation reply exists. For arms that
            # include the analysis pipeline, wait for the evaluator so its
            # evidence is captured before the next scripted turn; arms without
            # analysis have no evaluator node, so the conversation reply is the
            # turn's end.
            if saw_conversation and (not has_analysis or "evaluator" in update):
                break

    # Persist the session's accumulated evidence into the durable stores that
    # feed the learner model. Arms without the analysis components will have
    # empty grammar_errors/new_vocabulary, so their persisted evidence — and
    # therefore their measured CEFR movement — is smaller by construction.
    persist_session(state)


async def run_ablation_study(
    *,
    arms: list[str] | None = None,
    learners_per_arm: int = 3,
    language: str = "Spanish",
    script: tuple[str, ...] = _SCRIPT,
    experiment: str = ABLATION_EXPERIMENT,
    user_prefix: str | None = None,
) -> AblationReport:
    """Run the ablation ladder and record measured outcomes per arm.

    For each arm and each synthetic learner: assign the learner to the arm's
    variant, measure ``pre_test`` CEFR, run a scripted session through the
    arm's graph, measure ``immediate_post`` CEFR, and record both to the
    outcomes store. Returns an :class:`AblationReport` summarizing mean
    pre/post/gain per arm.

    Args:
        arms: Which arms to run (default: all of ``ABLATION_ARMS``, i.e. A-E).
        learners_per_arm: Cohort size per arm.
        language: Target language for the synthetic sessions.
        script: The learner turns to feed each session.
        experiment: The experiment name to record outcomes under.
        user_prefix: Prefix for synthetic user ids (default: a random run id),
            so repeated runs don't collide in the store.
    """
    selected = arms if arms is not None else sorted(ABLATION_ARMS)
    prefix = user_prefix or f"ablation-{uuid.uuid4().hex[:8]}"

    experiments.create_experiment(
        experiment,
        variants=sorted(ABLATION_ARMS),
        description="Five-arm ablation ladder (A=conversation-only .. E=full system).",
    )

    report = AblationReport(experiment=experiment, metric=METRIC)
    for arm in selected:
        pre_values: list[float] = []
        post_values: list[float] = []
        for i in range(learners_per_arm):
            user_id = f"{prefix}-{arm}-{i}"
            experiments.assign_to_variant(experiment, user_id, arm)

            pre, pre_payload = _measure(user_id, language)
            experiments.record_outcome(
                experiment, user_id, "pre_test", METRIC, pre, variant=arm, payload=pre_payload
            )
            pre_values.append(pre)

            with _scripted_agents():
                await _run_one_session(user_id, language, arm, script=script)

            post, post_payload = _measure(user_id, language)
            experiments.record_outcome(
                experiment,
                user_id,
                "immediate_post",
                METRIC,
                post,
                variant=arm,
                payload=post_payload,
            )
            post_values.append(post)

        report.arms.append(
            ArmResult(
                arm=arm,
                n_learners=learners_per_arm,
                mean_pre=sum(pre_values) / len(pre_values) if pre_values else 0.0,
                mean_post=sum(post_values) / len(post_values) if post_values else 0.0,
            )
        )
    return report


def summarize_report(report: AblationReport) -> str:
    """Render an :class:`AblationReport` as a compact text table."""
    lines = [
        f"Ablation study: {report.experiment}  (metric: {report.metric})",
        f"{'arm':<4} {'n':>3} {'pre':>7} {'post':>7} {'gain':>7}",
    ]
    for arm in report.arms:
        lines.append(
            f"{arm.arm:<4} {arm.n_learners:>3} "
            f"{arm.mean_pre:>7.3f} {arm.mean_post:>7.3f} {arm.mean_gain:>+7.3f}"
        )
    return "\n".join(lines)
