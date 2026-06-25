"""Unit tests for AnthropicProvider.embed and upstream-error logging.

Covers:
- AnthropicProvider.embed raises LLMError (no network call, no fabricated vector).
- generate APIError → WARNING logged with status/detail; api_key never appears.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from anthropic import APIError

from api.llm.anthropic_provider import AnthropicProvider
from api.llm.provider import ChatMessage, LLMError


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


# -- embed raises LLMError on Anthropic ----------------------------------------


async def test_embed_raises_llm_error_on_anthropic() -> None:
    """Anthropic has no embeddings API → LLMError, no client call."""
    tracking_client = MagicMock()
    provider = AnthropicProvider(client=tracking_client)

    with pytest.raises(LLMError) as exc_info:
        await provider.embed(
            ["hello world"],
            model="some-embed-model",
        )

    assert "Embeddings are not supported" in str(exc_info.value)
    # No method on the client should have been called
    tracking_client.assert_not_called()


# -- upstream-error logging for generate ---------------------------------------


async def test_generate_error_logs_warning_without_api_key(caplog: pytest.LogCaptureFixture) -> None:
    """generate APIError → WARNING logged with status/detail; api_key never appears."""
    sentinel_key = "sk-ant-SECRET-KEY-NEVER-LOG"
    mock_request = MagicMock()
    api_err = APIError("upstream error", request=mock_request, body={"error": "fail"})
    stub = _StubMessages(raise_error=api_err)
    client = _make_stub_client(stub)
    provider = AnthropicProvider(api_key=sentinel_key, client=client)

    with caplog.at_level(logging.WARNING, logger="api.llm.anthropic_provider"):
        with pytest.raises(LLMError):
            await provider.generate(
                [ChatMessage("user", "Hello")],
                model="claude-opus-4-8",
                max_tokens=512,
            )

    assert any("upstream error" in record.message for record in caplog.records)
    assert any("generate" in record.message for record in caplog.records)
    assert all(sentinel_key not in record.message for record in caplog.records)
