"""Unit tests for AzureOpenAIProvider.

AzureOpenAIProvider subclasses OpenAICompatibleProvider and overrides only
__init__ (builds AsyncAzureOpenAI). All operations (generate/embed/classify/
stream) are inherited unchanged.

Covers:
- With injected stub client, generate/embed/classify/stream behave like OpenAI.
- Without injected client, AsyncAzureOpenAI is constructed with
  azure_endpoint, api_version, max_retries, timeout.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from openai import APIError

from api.llm.azure_provider import AzureOpenAIProvider
from api.llm.provider import ChatMessage, Chunk, Completion, LLMError


class _StubCompletions:
    """Stub for ``client.chat.completions`` with an async ``create`` method."""

    def __init__(
        self,
        *,
        text: str = "Hello from Azure.",
        prompt_tokens: int = 10,
        completion_tokens: int = 5,
        finish_reason: str = "stop",
        raise_error: Exception | None = None,
        empty_choices: bool = False,
        stream_events: list | None = None,
    ) -> None:
        self._text = text
        self._prompt_tokens = prompt_tokens
        self._completion_tokens = completion_tokens
        self._finish_reason = finish_reason
        self._raise_error = raise_error
        self._empty_choices = empty_choices
        self._stream_events = stream_events
        self.last_kwargs: dict[str, object] = {}

    async def create(self, **kwargs: object) -> SimpleNamespace:
        self.last_kwargs = kwargs
        if self._raise_error is not None:
            raise self._raise_error
        if kwargs.get("stream"):
            return _AsyncIterator(self._stream_events or [])
        if self._empty_choices:
            return SimpleNamespace(choices=[], usage=None)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self._text),
                    finish_reason=self._finish_reason,
                )
            ],
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
    ) -> None:
        self._vectors = vectors or [[0.1, 0.2, 0.3]]
        self._raise_error = raise_error
        self.last_kwargs: dict[str, object] = {}

    async def create(self, **kwargs: object) -> SimpleNamespace:
        self.last_kwargs = kwargs
        if self._raise_error is not None:
            raise self._raise_error
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=v) for v in self._vectors],
        )


class _AsyncIterator:
    def __init__(self, events: list) -> None:
        self._events = events
        self._index = 0

    def __aiter__(self) -> _AsyncIterator:
        return self

    async def __anext__(self) -> object:
        if self._index >= len(self._events):
            raise StopAsyncIteration
        event = self._events[self._index]
        self._index += 1
        return event


def _make_stub_client(
    completions: _StubCompletions | None = None,
    embeddings: _StubEmbeddings | None = None,
) -> MagicMock:
    client = MagicMock()
    if completions is not None:
        client.chat.completions = completions
    if embeddings is not None:
        client.embeddings = embeddings
    return client


# -- generate (inherited from OpenAICompatibleProvider) ------------------------


async def test_azure_generate_returns_completion() -> None:
    """generate via Azure returns a Completion just like OpenAI."""
    stub = _StubCompletions(text="Azure response.", prompt_tokens=20, completion_tokens=8)
    client = _make_stub_client(completions=stub)
    provider = AzureOpenAIProvider(client=client)

    result = await provider.generate(
        [ChatMessage("user", "Hello")],
        model="my-deployment",
        max_tokens=512,
    )

    assert isinstance(result, Completion)
    assert result.text == "Azure response."
    assert result.model == "my-deployment"
    assert result.input_tokens == 20
    assert result.output_tokens == 8


# -- embed (inherited) ---------------------------------------------------------


async def test_azure_embed_returns_vectors() -> None:
    """embed via Azure returns vectors just like OpenAI."""
    stub = _StubEmbeddings(vectors=[[0.1, 0.2], [0.3, 0.4]])
    client = _make_stub_client(embeddings=stub)
    provider = AzureOpenAIProvider(client=client)

    result = await provider.embed(
        ["hello", "world"],
        model="my-embed-deployment",
    )

    assert result == [[0.1, 0.2], [0.3, 0.4]]


# -- classify (inherited) ------------------------------------------------------


async def test_azure_classify_returns_canonical_label() -> None:
    """classify via Azure returns the canonical-cased label."""
    stub = _StubCompletions(text="Support")
    client = _make_stub_client(completions=stub)
    provider = AzureOpenAIProvider(client=client)

    result = await provider.classify(
        "I need help",
        labels=["Sales", "Support", "Billing"],
        model="my-deployment",
    )

    assert result == "Support"


async def test_azure_classify_non_label_raises_llm_error() -> None:
    """classify with non-matching reply → LLMError."""
    stub = _StubCompletions(text="UnknownThing")
    client = _make_stub_client(completions=stub)
    provider = AzureOpenAIProvider(client=client)

    with pytest.raises(LLMError):
        await provider.classify(
            "I need help",
            labels=["Sales", "Support"],
            model="my-deployment",
        )


# -- stream (inherited) --------------------------------------------------------


async def test_azure_stream_yields_chunks() -> None:
    """stream via Azure yields Chunk deltas just like OpenAI."""
    stream_events = [
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="He"))]),
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="llo"))]),
    ]
    stub = _StubCompletions(stream_events=stream_events)
    client = _make_stub_client(completions=stub)
    provider = AzureOpenAIProvider(client=client)

    chunks: list[Chunk] = []
    async for chunk in provider.stream(
        [ChatMessage("user", "Hello")],
        model="my-deployment",
        max_tokens=512,
    ):
        chunks.append(chunk)

    assert chunks == [Chunk("He"), Chunk("llo")]


# -- error handling (inherited) ------------------------------------------------


async def test_azure_generate_wraps_api_error() -> None:
    """Azure generate APIError → LLMError."""
    mock_request = MagicMock()
    api_err = APIError("upstream error", request=mock_request, body={"error": "fail"})
    stub = _StubCompletions(raise_error=api_err)
    client = _make_stub_client(completions=stub)
    provider = AzureOpenAIProvider(client=client)

    with pytest.raises(LLMError):
        await provider.generate(
            [ChatMessage("user", "Hello")],
            model="my-deployment",
            max_tokens=512,
        )


async def test_azure_generate_error_logs_without_api_key(caplog: pytest.LogCaptureFixture) -> None:
    """Azure generate APIError → WARNING logged; api_key never appears."""
    sentinel_key = "sk-azure-SECRET-NEVER-LOG"
    mock_request = MagicMock()
    api_err = APIError("rate limited", request=mock_request, body={"error": "rate_limit"})
    stub = _StubCompletions(raise_error=api_err)
    client = _make_stub_client(completions=stub)
    provider = AzureOpenAIProvider(api_key=sentinel_key, client=client)

    with caplog.at_level(logging.WARNING, logger="api.llm.openai_provider"):
        with pytest.raises(LLMError):
            await provider.generate(
                [ChatMessage("user", "Hello")],
                model="my-deployment",
                max_tokens=512,
            )

    assert any("generate" in record.message for record in caplog.records)
    assert all(sentinel_key not in record.message for record in caplog.records)


# -- SDK construction (Azure-specific) -----------------------------------------


async def test_azure_constructs_async_azure_openai_with_correct_args() -> None:
    """Without injected client, AsyncAzureOpenAI is built with azure_endpoint,
    api_version, max_retries, timeout."""
    with patch("openai.AsyncAzureOpenAI") as MockAzure:
        MockAzure.return_value = MagicMock()
        AzureOpenAIProvider(
            api_key="sk-azure-key",
            azure_endpoint="https://my-resource.openai.azure.com",
            api_version="2024-02-01",
            max_retries=3,
            timeout=60.0,
        )
        MockAzure.assert_called_once_with(
            api_key="sk-azure-key",
            azure_endpoint="https://my-resource.openai.azure.com",
            api_version="2024-02-01",
            max_retries=3,
            timeout=60.0,
        )


# -- aclose (inherited from OpenAICompatibleProvider) ---------------------------


async def test_azure_aclose_calls_underlying_client_close() -> None:
    """aclose() awaits the injected client's close() exactly once -- inherited
    unchanged from OpenAICompatibleProvider (AsyncAzureOpenAI shares the same
    AsyncAPIClient.close() as AsyncOpenAI -- no override exists in
    ``openai/lib/azure.py``)."""
    client = MagicMock()
    client.close = AsyncMock()
    provider = AzureOpenAIProvider(client=client)

    await provider.aclose()

    client.close.assert_awaited_once_with()
