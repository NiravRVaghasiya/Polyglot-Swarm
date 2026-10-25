"""Multi-turn history through every turn runner (CLI, Gradio, ablation).

Each runner keeps the session's ``LearnerState`` itself and resends it to the
graph on every turn. If the compiled graph also has a checkpointer, LangGraph
merges that resent state into the checkpointed copy, and the ``messages``
add-reducer appends the whole history again — so the conversation model sees
earlier turns repeated. These tests pin that each prior turn reaches the model
exactly once. (The API runner is covered in ``tests/test_api/test_chat.py``.)
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from src.agents import conversation, cultural, evaluator, grammar, transfer, vocabulary
from src.config import settings
from src.llm.provider import LLMProvider

_SCRIPT = ("Hola", "Quiero un café", "Gracias")

_EXPECTED_LAST_PROMPT = [
    ("user", "Hola"),
    ("assistant", "reply 1"),
    ("user", "Quiero un café"),
    ("assistant", "reply 2"),
    ("user", "Gracias"),
]


class RecordingProvider(LLMProvider):
    """Records each conversation prompt (minus the system prompt)."""

    name = "recording"

    def __init__(self) -> None:
        self.prompts: list[list[tuple[str, str]]] = []

    def is_available(self) -> bool:
        return True

    async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
        if json_mode:
            return '{"errors": [], "words": [], "notes": [], "transfers": []}'
        self.prompts.append([(m.role, m.content) for m in messages if m.role != "system"])
        return f"reply {len(self.prompts)}"


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(settings, "data_dir", str(data_dir), raising=False)
    monkeypatch.setattr(settings, "profiles_dir", str(data_dir / "profiles"), raising=False)
    monkeypatch.setattr(settings, "db_path", str(data_dir / "polyglot.db"), raising=False)
    monkeypatch.setattr(settings, "chroma_path", str(data_dir / "chroma"), raising=False)
    return data_dir


@pytest.fixture
def recorder(monkeypatch):
    provider = RecordingProvider()
    for module in (conversation, grammar, vocabulary, cultural, evaluator, transfer):
        monkeypatch.setattr(module, "get_provider", lambda tier: provider)
    monkeypatch.setattr(cultural, "_persist_notes", lambda state, notes: None)
    return provider


async def test_gradio_runner_sends_each_turn_once(temp_storage, recorder):
    from src.main import _run_turn
    from src.orchestrator.lifecycle import build_initial_state

    state = build_initial_state("u-gradio", "Spanish")
    for message in _SCRIPT:
        await _run_turn(state, message)

    assert recorder.prompts[-1] == _EXPECTED_LAST_PROMPT


def test_cli_chat_sends_each_turn_once(temp_storage, recorder):
    from src.cli import app

    result = CliRunner().invoke(
        app,
        ["chat", "--language", "Spanish", "--user", "u-cli"],
        input="\n".join(_SCRIPT) + "\nquit\n",
    )

    assert result.exit_code == 0, result.output
    assert recorder.prompts[-1] == _EXPECTED_LAST_PROMPT


async def test_ablation_runner_sends_each_turn_once(temp_storage, monkeypatch):
    from src.experiments import runner

    prompts: list[list[tuple[str, str]]] = []
    original_generate = runner._ScriptedTutorProvider.generate

    async def recording_generate(self, messages, *, json_mode=False, **kwargs):
        if not json_mode:
            prompts.append([(m.role, m.content) for m in messages if m.role != "system"])
        return await original_generate(self, messages, json_mode=json_mode, **kwargs)

    monkeypatch.setattr(runner._ScriptedTutorProvider, "generate", recording_generate)

    with runner._scripted_agents():
        await runner._run_one_session("u-ablation", "Spanish", "E", script=_SCRIPT)

    user_turns = [content for role, content in prompts[-1] if role == "user"]
    assert user_turns == list(_SCRIPT)
