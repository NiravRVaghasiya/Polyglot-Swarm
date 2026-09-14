"""Smoke tests for the Gradio MVP callback wiring (graph/voice mocked)."""

from __future__ import annotations

import pytest

from src.config import settings


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(settings, "profiles_dir", str(data_dir / "profiles"), raising=False)
    monkeypatch.setattr(settings, "db_path", str(data_dir / "polyglot.db"), raising=False)
    monkeypatch.setattr(settings, "chroma_path", str(data_dir / "chroma"), raising=False)
    return data_dir


@pytest.fixture
def mock_llm(monkeypatch):
    from src.agents import (
        conversation,
        cultural,
        evaluator,
        grammar,
        transfer,
        vocabulary,
    )
    from src.llm.provider import LLMProvider

    class ScriptedProvider(LLMProvider):
        name = "scripted"

        def is_available(self) -> bool:
            return True

        async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
            if json_mode:
                return '{"errors": [], "words": [], "notes": [], "transfers": []}'
            return "¡Hola! Bienvenido."

    provider = ScriptedProvider()
    for module in (conversation, grammar, vocabulary, cultural, evaluator, transfer):
        monkeypatch.setattr(module, "get_provider", lambda tier: provider)
    monkeypatch.setattr(cultural, "_persist_notes", lambda state, notes: None)
    return provider


def test_build_ui_constructs():
    import gradio as gr

    from frontend.gradio_app import build_ui

    demo = build_ui()
    assert isinstance(demo, gr.Blocks)


def test_scenario_choices_include_free_and_scenarios():
    from frontend.gradio_app import _available_scenarios

    scenarios = _available_scenarios()
    assert any(s.id == "es_restaurant_ordering" for s in scenarios)


class TestChatText:
    def test_creates_session_and_replies(self, temp_storage, mock_llm):
        from frontend.gradio_app import chat_text

        box: dict = {}
        reply = chat_text("Hola", "Spanish", "", box)
        assert reply == "¡Hola! Bienvenido."
        assert box["state"] is not None
        assert box["state"]["turn_count"] >= 1

    def test_reuses_session_across_turns(self, temp_storage, mock_llm):
        from frontend.gradio_app import chat_text

        box: dict = {}
        chat_text("Hola", "Spanish", "", box)
        sid = box["state"]["session_id"]
        chat_text("¿Qué tal?", "Spanish", "", box)
        assert box["state"]["session_id"] == sid  # same session


class TestVoiceDegradation:
    def test_transcribe_no_audio(self):
        from frontend.gradio_app import transcribe_audio

        assert transcribe_audio(None, "Spanish") == ""

    def test_transcribe_missing_voice_dep_degrades(self, monkeypatch):
        from frontend.gradio_app import transcribe_audio

        # Force the STT import to fail -> message, not crash.
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "whisper":
                raise ImportError("no whisper")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        result = transcribe_audio("clip.wav", "Spanish")
        assert result.startswith("[voice unavailable")

    def test_synthesize_reply_none_when_unavailable(self, monkeypatch):
        from frontend.gradio_app import synthesize_reply

        import builtins

        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "edge_tts":
                raise ImportError("no edge_tts")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        assert synthesize_reply("hola", "Spanish") is None

    def test_synthesize_empty_text(self):
        from frontend.gradio_app import synthesize_reply

        assert synthesize_reply("", "Spanish") is None


class TestEndSession:
    def test_no_session(self):
        from frontend.gradio_app import end_session

        assert end_session({}) == "No active session."

    def test_returns_report(self, temp_storage, mock_llm):
        from frontend.gradio_app import chat_text, end_session

        box: dict = {}
        chat_text("Hola una mesa", "Spanish", "", box)
        report = end_session(box)
        assert "Session Report" in report
        assert box["state"] is None
