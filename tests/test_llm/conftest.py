"""Shared fixtures for LLM provider tests.

The concrete provider SDKs (langchain-anthropic, langchain-google-genai,
langchain-community) may not be installed in the test environment. Providers
import those SDKs lazily inside methods, so tests inject lightweight fake
modules into ``sys.modules`` to satisfy those imports without any network or
real dependency.
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass

import pytest


@dataclass
class FakeResponse:
    """Mimics a LangChain chat model response object."""

    content: str


class RecordingChatModel:
    """A stand-in chat model that records the last invocation.

    Instances are created by the fake SDK factories below. Each captures the
    constructor kwargs and, on ``ainvoke``, the messages it was called with,
    then returns a canned response so tests can assert on both sides.
    """

    last_instance: "RecordingChatModel | None" = None

    def __init__(self, **kwargs):
        self.init_kwargs = kwargs
        self.invoked_with = None
        self.reply = "canned reply"
        type(self).last_instance = self

    async def ainvoke(self, messages):
        self.invoked_with = messages
        return FakeResponse(content=self.reply)


def _install_fake_langchain_core() -> None:
    """Install fake langchain_core.messages with the standard message classes."""
    if "langchain_core.messages" in sys.modules:
        return

    core = types.ModuleType("langchain_core")
    messages_mod = types.ModuleType("langchain_core.messages")

    class _BaseMessage:
        def __init__(self, content):
            self.content = content

        def __repr__(self):
            return f"{type(self).__name__}({self.content!r})"

    for cls_name in ("SystemMessage", "HumanMessage", "AIMessage"):
        setattr(messages_mod, cls_name, type(cls_name, (_BaseMessage,), {}))

    core.messages = messages_mod
    sys.modules["langchain_core"] = core
    sys.modules["langchain_core.messages"] = messages_mod


@pytest.fixture
def fake_langchain(monkeypatch):
    """Install fake langchain SDK modules and expose the recording model.

    Returns the ``RecordingChatModel`` class so tests can read
    ``RecordingChatModel.last_instance`` after invoking a provider.
    """
    _install_fake_langchain_core()

    # langchain_anthropic.ChatAnthropic
    anthropic_mod = types.ModuleType("langchain_anthropic")
    anthropic_mod.ChatAnthropic = RecordingChatModel
    monkeypatch.setitem(sys.modules, "langchain_anthropic", anthropic_mod)

    # langchain_google_genai.ChatGoogleGenerativeAI
    genai_mod = types.ModuleType("langchain_google_genai")
    genai_mod.ChatGoogleGenerativeAI = RecordingChatModel
    monkeypatch.setitem(sys.modules, "langchain_google_genai", genai_mod)

    # langchain_community.chat_models.ChatOllama
    community_mod = types.ModuleType("langchain_community")
    chat_models_mod = types.ModuleType("langchain_community.chat_models")
    chat_models_mod.ChatOllama = RecordingChatModel
    community_mod.chat_models = chat_models_mod
    monkeypatch.setitem(sys.modules, "langchain_community", community_mod)
    monkeypatch.setitem(sys.modules, "langchain_community.chat_models", chat_models_mod)

    return RecordingChatModel
