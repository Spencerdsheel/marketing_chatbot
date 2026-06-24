"""OpenAI-compatible provider implementation.

Uses the async ``openai`` SDK. Does NOT send ``temperature`` or ``top_p``.
Supports any OpenAI-wire endpoint (OpenAI, OpenCode Zen, local Ollama) via
an optional ``base_url``.
"""
from __future__ import annotations

from typing import Any

from openai import APIError

from api.llm.provider import ChatMessage, Completion, LLMError


class OpenAICompatibleProvider:
    """OpenAI-wire backend for ``LLMProvider.generate``."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        client: Any | None = None,
    ) -> None:
        if client is not None:
            self._client = client
        else:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def generate(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        max_tokens: int,
    ) -> Completion:
        try:
            resp = await self._client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": m.role, "content": m.content} for m in messages],
            )
        except APIError as exc:
            raise LLMError("LLM request failed.") from exc

        if not resp.choices:
            raise LLMError("LLM request failed.")

        choice = resp.choices[0]
        text = choice.message.content or ""
        return Completion(
            text=text,
            model=model,
            input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
            output_tokens=resp.usage.completion_tokens if resp.usage else 0,
            stop_reason=choice.finish_reason,
        )
