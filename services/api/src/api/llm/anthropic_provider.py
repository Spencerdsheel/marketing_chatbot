"""Anthropic provider implementation.

Uses the async ``anthropic`` SDK. Does NOT send ``temperature``, ``top_p``,
``top_k``, or ``thinking``/``budget_tokens`` (they return 400 on
``claude-opus-4-8``).

Anthropic has no embeddings API -- ``embed`` raises an explicit ``LLMError``.
"""
from __future__ import annotations

from typing import Any

from anthropic import APIError
from common.logging import get_logger

from api.llm.provider import ChatMessage, Completion, LLMError, Vector

_log = get_logger(__name__)


class AnthropicProvider:
    """Anthropic Claude backend for ``LLMProvider.generate``."""

    def __init__(self, *, api_key: str | None = None, client: Any | None = None) -> None:
        if client is not None:
            self._client = client
        else:
            from anthropic import AsyncAnthropic
            self._client = AsyncAnthropic(api_key=api_key)

    async def generate(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        max_tokens: int,
    ) -> Completion:
        try:
            resp = await self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": m.role, "content": m.content} for m in messages],
            )
        except APIError as exc:
            _log.warning(
                "LLM upstream call failed: provider=anthropic op=generate"
                " model=%s status=%s detail=%s",
                model,
                getattr(exc, "status_code", None),
                str(exc),
            )
            raise LLMError("LLM request failed.") from exc

        text = "".join(b.text for b in resp.content if b.type == "text")
        return Completion(
            text=text,
            model=model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            stop_reason=resp.stop_reason,
        )

    async def embed(
        self,
        texts: list[str],
        *,
        model: str,
    ) -> list[Vector]:
        raise LLMError(
            "Embeddings are not supported by the Anthropic provider; "
            "configure an OpenAI-compatible embeddings endpoint.",
        )
