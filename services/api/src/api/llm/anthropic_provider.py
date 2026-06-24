"""Anthropic provider implementation.

Uses the async ``anthropic`` SDK. Does NOT send ``temperature``, ``top_p``,
``top_k``, or ``thinking``/``budget_tokens`` (they return 400 on
``claude-opus-4-8``).
"""
from __future__ import annotations

from typing import Any

from anthropic import APIError

from api.llm.provider import ChatMessage, Completion, LLMError


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
            raise LLMError("LLM request failed.") from exc

        text = "".join(b.text for b in resp.content if b.type == "text")
        return Completion(
            text=text,
            model=model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            stop_reason=resp.stop_reason,
        )
