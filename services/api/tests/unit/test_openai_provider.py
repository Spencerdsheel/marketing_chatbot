"""Unit tests for OpenAICompatibleProvider.generate.

Uses a stub client to avoid real network calls. Verifies:
- Returns Completion with text + usage + finish_reason.
- Call kwargs contain ONLY model/max_tokens/messages (no temperature/top_p).
- content=None → text == "".
- Empty choices → LLMError.
- openai.APIError → LLMError (no fabricated text).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from openai import APIError

from api.llm.openai_provider import OpenAICompatibleProvider
from api.llm.provider import ChatMessage, Completion, LLMError


class _StubCompletions:
    """Stub for ``client.chat.completions`` with an async ``create`` method."""

    def __init__(
        self,
        *,
        text: str = "Hello from the stub.",
        prompt_tokens: int = 10,
        completion_tokens: int = 5,
        finish_reason: str = "stop",
        raise_error: Exception | None = None,
        empty_choices: bool = False,
        content_none: bool = False,
    ) -> None:
        self._text = text
        self._prompt_tokens = prompt_tokens
        self._completion_tokens = completion_tokens
        self._finish_reason = finish_reason
        self._raise_error = raise_error
        self._empty_choices = empty_choices
        self._content_none = content_none
        self.last_kwargs: dict[str, object] = {}

    async def create(self, **kwargs: object) -> SimpleNamespace:
        self.last_kwargs = kwargs
        if self._raise_error is not None:
            raise self._raise_error
        if self._empty_choices:
            return SimpleNamespace(choices=[], usage=None)
        message = SimpleNamespace(content=None if self._content_none else self._text)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason=self._finish_reason)],
            usage=SimpleNamespace(
                prompt_tokens=self._prompt_tokens,
                completion_tokens=self._completion_tokens,
            ),
        )


def _make_stub_client(completions: _StubCompletions) -> MagicMock:
    """Build a mock client whose ``chat.completions`` attribute is the stub."""
    client = MagicMock()
    client.chat.completions = completions
    return client


async def test_generate_returns_completion_with_text_and_usage() -> None:
    """generate returns a Completion with the message text + usage counts."""
    stub = _StubCompletions(text="Hi there.", prompt_tokens=20, completion_tokens=8)
    client = _make_stub_client(stub)
    provider = OpenAICompatibleProvider(client=client)

    result = await provider.generate(
        [ChatMessage("user", "Hello")],
        model="gpt-4o",
        max_tokens=512,
    )

    assert isinstance(result, Completion)
    assert result.text == "Hi there."
    assert result.model == "gpt-4o"
    assert result.input_tokens == 20
    assert result.output_tokens == 8
    assert result.stop_reason == "stop"


async def test_generate_does_not_send_forbidden_params() -> None:
    """The call kwargs must contain ONLY model, max_tokens, messages."""
    stub = _StubCompletions()
    client = _make_stub_client(stub)
    provider = OpenAICompatibleProvider(client=client)

    await provider.generate(
        [ChatMessage("user", "Hello")],
        model="gpt-4o",
        max_tokens=512,
    )

    assert set(stub.last_kwargs.keys()) == {"model", "max_tokens", "messages"}
    for forbidden in ("temperature", "top_p", "top_k", "thinking"):
        assert forbidden not in stub.last_kwargs


async def test_generate_content_none_yields_empty_text() -> None:
    """When message.content is None, text should be empty string."""
    stub = _StubCompletions(content_none=True)
    client = _make_stub_client(stub)
    provider = OpenAICompatibleProvider(client=client)

    result = await provider.generate(
        [ChatMessage("user", "Hello")],
        model="gpt-4o",
        max_tokens=512,
    )

    assert result.text == ""


async def test_generate_empty_choices_raises_llm_error() -> None:
    """Empty choices list → LLMError (no fabricated text)."""
    stub = _StubCompletions(empty_choices=True)
    client = _make_stub_client(stub)
    provider = OpenAICompatibleProvider(client=client)

    with pytest.raises(LLMError):
        await provider.generate(
            [ChatMessage("user", "Hello")],
            model="gpt-4o",
            max_tokens=512,
        )


async def test_generate_wraps_api_error_in_llm_error() -> None:
    """An openai.APIError is wrapped in LLMError -- no fabricated text."""
    mock_request = MagicMock()
    api_err = APIError(
        message="upstream error",
        request=mock_request,
        body={"error": "fail"},
    )
    stub = _StubCompletions(raise_error=api_err)
    client = _make_stub_client(stub)
    provider = OpenAICompatibleProvider(client=client)

    with pytest.raises(LLMError):
        await provider.generate(
            [ChatMessage("user", "Hello")],
            model="gpt-4o",
            max_tokens=512,
        )
