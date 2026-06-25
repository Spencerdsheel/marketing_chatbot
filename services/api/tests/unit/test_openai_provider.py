"""Unit tests for OpenAICompatibleProvider.generate and embed.

Uses a stub client to avoid real network calls. Verifies:
- Returns Completion with text + usage + finish_reason.
- Call kwargs contain ONLY model/max_tokens/messages (no temperature/top_p).
- content=None → text == "".
- Empty choices → LLMError.
- openai.APIError → LLMError (no fabricated text).
- embed returns vectors in order; kwargs are exactly {model, input}.
- Empty embeddings data → LLMError.
- Upstream-error logging emits WARNING with status/detail; api_key never logged.
"""
from __future__ import annotations

import logging
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


class _StubEmbeddings:
    """Stub for ``client.embeddings`` with an async ``create`` method."""

    def __init__(
        self,
        *,
        vectors: list[list[float]] | None = None,
        raise_error: Exception | None = None,
        empty_data: bool = False,
    ) -> None:
        self._vectors = vectors or [[0.1, 0.2, 0.3]]
        self._raise_error = raise_error
        self._empty_data = empty_data
        self.last_kwargs: dict[str, object] = {}

    async def create(self, **kwargs: object) -> SimpleNamespace:
        self.last_kwargs = kwargs
        if self._raise_error is not None:
            raise self._raise_error
        if self._empty_data:
            return SimpleNamespace(data=[])
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=v) for v in self._vectors],
        )


def _make_stub_client(
    completions: _StubCompletions | None = None,
    embeddings: _StubEmbeddings | None = None,
) -> MagicMock:
    """Build a mock client with optional completions and embeddings stubs."""
    client = MagicMock()
    if completions is not None:
        client.chat.completions = completions
    if embeddings is not None:
        client.embeddings = embeddings
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
    client = _make_stub_client(completions=stub)
    provider = OpenAICompatibleProvider(client=client)

    with pytest.raises(LLMError):
        await provider.generate(
            [ChatMessage("user", "Hello")],
            model="gpt-4o",
            max_tokens=512,
        )


# -- embed tests ---------------------------------------------------------------


async def test_embed_returns_vectors_in_order() -> None:
    """embed returns the vectors in the same order as input texts."""
    stub = _StubEmbeddings(vectors=[[0.1, 0.2], [0.3, 0.4, 0.5]])
    client = _make_stub_client(embeddings=stub)
    provider = OpenAICompatibleProvider(client=client)

    result = await provider.embed(
        ["hello", "world"],
        model="text-embedding-3-small",
    )

    assert result == [[0.1, 0.2], [0.3, 0.4, 0.5]]


async def test_embed_kwargs_are_exactly_model_and_input() -> None:
    """The call kwargs must contain ONLY model and input."""
    stub = _StubEmbeddings()
    client = _make_stub_client(embeddings=stub)
    provider = OpenAICompatibleProvider(client=client)

    await provider.embed(
        ["hello world"],
        model="nomic-embed-text",
    )

    assert set(stub.last_kwargs.keys()) == {"model", "input"}
    assert stub.last_kwargs["model"] == "nomic-embed-text"
    assert stub.last_kwargs["input"] == ["hello world"]


async def test_embed_empty_data_raises_llm_error() -> None:
    """Empty embeddings data → LLMError (no fabricated vector)."""
    stub = _StubEmbeddings(empty_data=True)
    client = _make_stub_client(embeddings=stub)
    provider = OpenAICompatibleProvider(client=client)

    with pytest.raises(LLMError):
        await provider.embed(
            ["hello"],
            model="nomic-embed-text",
        )


async def test_embed_wraps_api_error_in_llm_error() -> None:
    """An openai.APIError on embed is wrapped in LLMError."""
    mock_request = MagicMock()
    api_err = APIError(
        message="bad model",
        request=mock_request,
        body={"error": "invalid_model"},
    )
    stub = _StubEmbeddings(raise_error=api_err)
    client = _make_stub_client(embeddings=stub)
    provider = OpenAICompatibleProvider(client=client)

    with pytest.raises(LLMError):
        await provider.embed(
            ["hello"],
            model="nonexistent-model",
        )


# -- upstream-error logging tests ----------------------------------------------


async def test_generate_error_logs_warning_without_api_key(caplog: pytest.LogCaptureFixture) -> None:
    """generate APIError → WARNING logged with status/detail; api_key never appears."""
    sentinel_key = "sk-SECRET-KEY-NEVER-LOG"
    mock_request = MagicMock()
    api_err = APIError(
        message="rate limited",
        request=mock_request,
        body={"error": "rate_limit"},
    )
    stub = _StubCompletions(raise_error=api_err)
    client = _make_stub_client(completions=stub)
    provider = OpenAICompatibleProvider(api_key=sentinel_key, client=client)

    with caplog.at_level(logging.WARNING, logger="api.llm.openai_provider"):
        with pytest.raises(LLMError):
            await provider.generate(
                [ChatMessage("user", "Hello")],
                model="gpt-4o",
                max_tokens=512,
            )

    assert any("rate limited" in record.message for record in caplog.records)
    assert any("generate" in record.message for record in caplog.records)
    assert all(sentinel_key not in record.message for record in caplog.records)


async def test_embed_error_logs_warning_without_api_key(caplog: pytest.LogCaptureFixture) -> None:
    """embed APIError → WARNING logged with status/detail; api_key never appears."""
    sentinel_key = "sk-SECRET-KEY-NEVER-LOG"
    mock_request = MagicMock()
    api_err = APIError(
        message="bad model",
        request=mock_request,
        body={"error": "invalid_model"},
    )
    stub = _StubEmbeddings(raise_error=api_err)
    client = _make_stub_client(embeddings=stub)
    provider = OpenAICompatibleProvider(api_key=sentinel_key, client=client)

    with caplog.at_level(logging.WARNING, logger="api.llm.openai_provider"):
        with pytest.raises(LLMError):
            await provider.embed(
                ["hello"],
                model="nonexistent",
            )

    assert any("bad model" in record.message for record in caplog.records)
    assert any("embed" in record.message for record in caplog.records)
    assert all(sentinel_key not in record.message for record in caplog.records)
