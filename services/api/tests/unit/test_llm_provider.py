"""Unit tests for AnthropicProvider.generate.

Uses a stub client to avoid real network calls. Verifies:
- Returns Completion with joined text + usage.
- Call kwargs do NOT contain temperature, top_p, top_k, or thinking.
- anthropic.APIError → LLMError (no fabricated text).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from anthropic import APIError

from api.llm.anthropic_provider import AnthropicProvider
from api.llm.provider import ChatMessage, Completion, LLMError


class _StubMessages:
    """Stub for ``client.messages`` with an async ``create`` method."""

    def __init__(
        self,
        *,
        text: str = "Hello from the stub.",
        input_tokens: int = 10,
        output_tokens: int = 5,
        stop_reason: str = "end_turn",
        raise_error: Exception | None = None,
    ) -> None:
        self._text = text
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self._stop_reason = stop_reason
        self._raise_error = raise_error
        self.last_kwargs: dict[str, object] = {}

    async def create(self, **kwargs: object) -> SimpleNamespace:
        self.last_kwargs = kwargs
        if self._raise_error is not None:
            raise self._raise_error
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self._text)],
            usage=SimpleNamespace(
                input_tokens=self._input_tokens,
                output_tokens=self._output_tokens,
            ),
            stop_reason=self._stop_reason,
        )


def _make_stub_client(messages: _StubMessages) -> MagicMock:
    """Build a mock client whose ``messages`` attribute is the stub."""
    client = MagicMock()
    client.messages = messages
    return client


async def test_generate_returns_completion_with_text_and_usage() -> None:
    """generate returns a Completion with the joined text + usage counts."""
    stub = _StubMessages(text="Hi there.", input_tokens=20, output_tokens=8)
    client = _make_stub_client(stub)
    provider = AnthropicProvider(client=client)

    result = await provider.generate(
        [ChatMessage("user", "Hello")],
        model="claude-opus-4-8",
        max_tokens=512,
    )

    assert isinstance(result, Completion)
    assert result.text == "Hi there."
    assert result.model == "claude-opus-4-8"
    assert result.input_tokens == 20
    assert result.output_tokens == 8
    assert result.stop_reason == "end_turn"


async def test_generate_does_not_send_forbidden_params() -> None:
    """The call kwargs must NOT contain temperature, top_p, top_k, or thinking."""
    stub = _StubMessages()
    client = _make_stub_client(stub)
    provider = AnthropicProvider(client=client)

    await provider.generate(
        [ChatMessage("user", "Hello")],
        model="claude-opus-4-8",
        max_tokens=512,
    )

    for forbidden in ("temperature", "top_p", "top_k", "thinking", "budget_tokens"):
        assert forbidden not in stub.last_kwargs, f"forbidden param {forbidden} found in kwargs"


async def test_generate_wraps_api_error_in_llm_error() -> None:
    """An anthropic.APIError is wrapped in LLMError -- no fabricated text."""
    mock_request = MagicMock()
    api_err = APIError("upstream error", request=mock_request, body={"error": "fail"})
    stub = _StubMessages(raise_error=api_err)
    client = _make_stub_client(stub)
    provider = AnthropicProvider(client=client)

    with pytest.raises(LLMError):
        await provider.generate(
            [ChatMessage("user", "Hello")],
            model="claude-opus-4-8",
            max_tokens=512,
        )


async def test_generate_joins_multiple_text_blocks() -> None:
    """Multiple text content blocks are concatenated."""
    stub = _StubMessages()

    async def create(**kwargs: object) -> SimpleNamespace:
        stub.last_kwargs = kwargs
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="text", text="Part 1. "),
                SimpleNamespace(type="text", text="Part 2."),
                SimpleNamespace(type="tool_use", id="x", name="tool", input={}),
            ],
            usage=SimpleNamespace(input_tokens=5, output_tokens=3),
            stop_reason="end_turn",
        )

    stub.create = create  # type: ignore[method-assign]
    client = _make_stub_client(stub)
    provider = AnthropicProvider(client=client)

    result = await provider.generate(
        [ChatMessage("user", "Hello")],
        model="claude-opus-4-8",
        max_tokens=512,
    )

    assert result.text == "Part 1. Part 2."
