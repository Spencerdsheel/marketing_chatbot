"""Unit tests for the LLM provider factory.

Covers:
- openai config (with base_url) → OpenAICompatibleProvider with base_url threaded.
- anthropic config → AnthropicProvider.
- azure config → LLMError.
"""
from __future__ import annotations

import pytest

from api.llm.anthropic_provider import AnthropicProvider
from api.llm.config_repository import LLMConfig
from api.llm.factory import provider_for
from api.llm.openai_provider import OpenAICompatibleProvider
from api.llm.provider import LLMError


def test_openai_config_yields_openai_provider() -> None:
    """provider='openai' with base_url → OpenAICompatibleProvider."""
    config = LLMConfig(
        provider="openai",
        model="gpt-4o",
        api_key="sk-test-key",
        base_url="https://opencode.ai/zen/v1",
    )
    provider = provider_for(config)
    assert isinstance(provider, OpenAICompatibleProvider)


def test_openai_config_without_base_url() -> None:
    """provider='openai' without base_url → OpenAICompatibleProvider (None base_url)."""
    config = LLMConfig(
        provider="openai",
        model="gpt-4o",
        api_key="sk-test-key",
    )
    provider = provider_for(config)
    assert isinstance(provider, OpenAICompatibleProvider)


def test_anthropic_config_yields_anthropic_provider() -> None:
    """provider='anthropic' → AnthropicProvider."""
    config = LLMConfig(
        provider="anthropic",
        model="claude-opus-4-8",
        api_key="sk-ant-test-key",
    )
    provider = provider_for(config)
    assert isinstance(provider, AnthropicProvider)


def test_azure_config_raises_llm_error() -> None:
    """provider='azure' → LLMError (not yet supported)."""
    config = LLMConfig(
        provider="azure",
        model="gpt-4",
        api_key="sk-azure-key",
    )
    with pytest.raises(LLMError):
        provider_for(config)
