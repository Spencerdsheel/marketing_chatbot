"""Provider factory -- resolves an ``LLMProvider`` from an ``LLMConfig``.

Reads ``llm_max_retries`` and ``llm_timeout_seconds`` from ``ApiSettings``
and threads them into each provider constructor (SDK-level resilience).
"""
from __future__ import annotations

from api.config import get_api_settings
from api.llm.anthropic_provider import AnthropicProvider
from api.llm.azure_provider import AzureOpenAIProvider
from api.llm.config_repository import LLMConfig
from api.llm.openai_provider import OpenAICompatibleProvider
from api.llm.provider import LLMError, LLMProvider


def provider_for(config: LLMConfig) -> LLMProvider:
    """Return an ``LLMProvider`` for the given config.

    Raises ``LLMError`` for providers not yet implemented or for Azure with
    missing required configuration.
    """
    settings = get_api_settings()

    if config.provider == "anthropic":
        return AnthropicProvider(
            api_key=config.api_key,
            max_retries=settings.llm_max_retries,
            timeout=settings.llm_timeout_seconds,
        )
    if config.provider == "openai":
        return OpenAICompatibleProvider(
            api_key=config.api_key,
            base_url=config.base_url,
            max_retries=settings.llm_max_retries,
            timeout=settings.llm_timeout_seconds,
        )
    if config.provider == "azure":
        if not config.base_url or not config.api_version:
            raise LLMError(
                "Azure requires base_url (azure_endpoint) and api_version.",
            )
        return AzureOpenAIProvider(
            api_key=config.api_key,
            azure_endpoint=config.base_url,
            api_version=config.api_version,
            max_retries=settings.llm_max_retries,
            timeout=settings.llm_timeout_seconds,
        )
    raise LLMError("Provider not yet supported.")
