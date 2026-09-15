"""Phase 22 tests: conversation history windowing.

Sending the whole transcript since session start on every turn grows cost
and latency unboundedly with session length; conversation_node now caps how
many recent messages it sends.
"""

from __future__ import annotations

from src.agents import conversation
from src.agents.conversation import MAX_HISTORY_MESSAGES, _windowed_history
from src.llm.provider import LLMProvider, Message


class RecordingProvider(LLMProvider):
    name = "recording"

    def __init__(self, reply: str = "reply"):
        self.reply = reply
        self.calls: list[dict] = []

    def is_available(self) -> bool:
        return True

    async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
        self.calls.append({"messages": messages})
        return self.reply


def _base_state(**overrides):
    state = {
        "session_id": "s1",
        "language": "Spanish",
        "mode": "conversation",
        "messages": [],
        "current_scenario": {"persona": {"name": "Ana", "role": "waiter"}},
        "cefr_level": "A2",
        "turn_count": 0,
        "last_user_input": "Hola",
        "agent_response": "",
    }
    state.update(overrides)
    return state


def _history(n: int) -> list[dict]:
    history = []
    for i in range(n):
        history.append({"role": "user", "content": f"user turn {i}"})
        history.append({"role": "assistant", "content": f"assistant turn {i}"})
    return history


class TestWindowedHistoryHelper:
    def test_short_history_is_unchanged(self):
        history = _history(3)  # 6 messages, under the cap
        assert _windowed_history(history) == history

    def test_long_history_is_truncated_to_the_cap(self):
        history = _history(50)  # 100 messages, well over the cap
        windowed = _windowed_history(history)
        assert len(windowed) == MAX_HISTORY_MESSAGES

    def test_truncation_keeps_the_most_recent_messages(self):
        history = _history(50)
        windowed = _windowed_history(history)
        assert windowed == history[-MAX_HISTORY_MESSAGES:]
        assert windowed[-1]["content"] == history[-1]["content"]

    def test_exactly_at_the_cap_is_unchanged(self):
        history = [{"role": "user", "content": str(i)} for i in range(MAX_HISTORY_MESSAGES)]
        assert _windowed_history(history) == history

    def test_empty_history(self):
        assert _windowed_history([]) == []


class TestConversationNodeSendsWindowedHistory:
    async def test_long_transcript_is_capped_in_the_actual_llm_call(self, monkeypatch):
        provider = RecordingProvider()
        monkeypatch.setattr(conversation, "get_provider", lambda tier: provider)

        state = _base_state(messages=_history(50))
        await conversation.conversation_node(state)

        sent = provider.calls[0]["messages"]
        # First message is the system prompt; the rest is the (windowed)
        # history plus the current user input.
        history_messages = sent[1:]
        assert len(history_messages) == MAX_HISTORY_MESSAGES + 1  # + current input
        assert isinstance(history_messages[0], Message)

    async def test_short_transcript_is_sent_in_full(self, monkeypatch):
        provider = RecordingProvider()
        monkeypatch.setattr(conversation, "get_provider", lambda tier: provider)

        state = _base_state(messages=_history(3))  # 6 messages, under the cap
        await conversation.conversation_node(state)

        sent = provider.calls[0]["messages"]
        history_messages = sent[1:]
        assert len(history_messages) == 6 + 1  # + current input

    async def test_windowing_does_not_affect_the_reply_or_turn_count(self, monkeypatch):
        provider = RecordingProvider(reply="hola de nuevo")
        monkeypatch.setattr(conversation, "get_provider", lambda tier: provider)

        state = _base_state(messages=_history(50), turn_count=50)
        result = await conversation.conversation_node(state)

        assert result["agent_response"] == "hola de nuevo"
        assert result["turn_count"] == 51
