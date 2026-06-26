"""OpenAI-compatible provider implementation.

Uses the async ``openai`` SDK. Does NOT send ``temperature`` or ``top_p``.
Supports any OpenAI-wire endpoint (OpenAI, OpenCode Zen, local Ollama) via
an optional ``base_url``.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from common.logging import get_logger
from openai import APIError

from api.llm.provider import (
    ChatMessage,
    Chunk,
    Completion,
    Label,
    LLMError,
    Vector,
)

_log = get_logger(__name__)

_CLASSIFY_MAX_TOKENS = 256
_CLASSIFY_REPLY_LOG_LIMIT = 120


class OpenAICompatibleProvider:
    """OpenAI-wire backend for ``LLMProvider.generate``, ``embed``, ``classify``, and ``stream``."""

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
            _log.warning(
                "LLM upstream call failed: provider=openai op=generate"
                " model=%s status=%s detail=%s",
                model,
                getattr(exc, "status_code", None),
                str(exc),
            )
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

    async def embed(
        self,
        texts: list[str],
        *,
        model: str,
    ) -> list[Vector]:
        try:
            resp = await self._client.embeddings.create(
                model=model,
                input=texts,
            )
        except APIError as exc:
            _log.warning(
                "LLM upstream call failed: provider=openai op=embed model=%s status=%s detail=%s",
                model,
                getattr(exc, "status_code", None),
                str(exc),
            )
            raise LLMError("LLM request failed.") from exc

        if not resp.data:
            raise LLMError("LLM request failed.")

        return [d.embedding for d in resp.data]

    async def classify(
        self,
        text: str,
        labels: list[str],
        *,
        model: str,
    ) -> Label:
        if not labels:
            raise LLMError("LLM request failed.")

        labels_str = ", ".join(labels)
        instruction = (
            f"Classify the text into exactly one of these labels: {labels_str}. "
            "Reply with only the label, nothing else."
        )
        chat_messages = [
            ChatMessage("system", instruction),
            ChatMessage("user", text),
        ]

        try:
            resp = await self._client.chat.completions.create(
                model=model,
                max_tokens=_CLASSIFY_MAX_TOKENS,
                messages=[{"role": m.role, "content": m.content} for m in chat_messages],
            )
        except APIError as exc:
            _log.warning(
                "LLM upstream call failed: provider=openai op=classify"
                " model=%s status=%s detail=%s",
                model,
                getattr(exc, "status_code", None),
                str(exc),
            )
            raise LLMError("LLM request failed.") from exc

        if not resp.choices:
            raise LLMError("LLM request failed.")

        reply = (resp.choices[0].message.content or "").strip()
        for label in labels:
            if reply.lower() == label.lower():
                return label
        _log.warning(
            "LLM classify produced no matching label: provider=%s model=%s labels=%s reply=%r",
            "openai",
            model,
            labels,
            reply[:_CLASSIFY_REPLY_LOG_LIMIT],
        )
        raise LLMError("LLM request failed.")

    async def stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        max_tokens: int,
    ) -> AsyncIterator[Chunk]:
        try:
            stream = await self._client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": m.role, "content": m.content} for m in messages],
                stream=True,
            )
        except APIError as exc:
            _log.warning(
                "LLM upstream call failed: provider=openai op=stream"
                " model=%s status=%s detail=%s",
                model,
                getattr(exc, "status_code", None),
                str(exc),
            )
            raise LLMError("LLM request failed.") from exc

        try:
            async for event in stream:
                if event.choices:
                    delta = event.choices[0].delta
                    content = getattr(delta, "content", None)
                    if content:
                        yield Chunk(text=content)
        except APIError as exc:
            _log.warning(
                "LLM upstream call failed: provider=openai op=stream"
                " model=%s status=%s detail=%s",
                model,
                getattr(exc, "status_code", None),
                str(exc),
            )
            raise LLMError("LLM request failed.") from exc
