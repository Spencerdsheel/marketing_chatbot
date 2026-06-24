"""Provider factory -- resolves an ``LLMProvider`` from an ``LLMConfig``."""
from __future__ import annotations

from api.llm.anthropic_provider import AnthropicProvider
from api.llm.config_repository import LLMConfig
from api.llm.openai_provider import OpenAICompatibleProvider
from api.llm.provider import LLMError, LLMProvider


def provider_for(config: LLMConfig) -> LLMProvider:
    """Return an ``LLMProvider`` for the given config.

    Raises ``LLMError`` for providers not yet implemented.
    """
    if config.provider == "anthropic":
        return AnthropicProvider(api_key=config.api_key)
    if config.provider == "openai":
        return OpenAICompatibleProvider(api_key=config.api_key, base_url=config.base_url)
    raise LLMError("Provider not yet supported.")
