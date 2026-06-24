"""LLM provider boundary -- provider-agnostic Protocol + domain types.

No default provider is configured. A tenant with no ``tenant_llm_configs`` row
gets an explicit error, never a fabricated answer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from common.errors import AppException


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    stop_reason: str | None = None


class LLMProvider(Protocol):
    async def generate(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        max_tokens: int,
    ) -> Completion: ...


class LLMError(AppException):
    """Provider-level failure (network, upstream error, unsupported provider)."""

    code = "LLM_ERROR"
    http_status = 502
    default_message = "LLM request failed."
