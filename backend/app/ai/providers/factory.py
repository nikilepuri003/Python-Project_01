from __future__ import annotations

from typing import Any

from app.ai.providers.anthropic import AnthropicProvider
from app.ai.providers.base import AIProvider
from app.ai.providers.gemini import GeminiProvider
from app.ai.providers.mock import MockAIProvider
from app.ai.providers.openai import OpenAIProvider
from app.core.config import get_settings


def get_ai_provider(provider_name: str | None = None) -> AIProvider:
    settings = get_settings()
    provider = (provider_name or settings.ai_provider or "mock").lower()
    registry: dict[str, Any] = {
        "openai": OpenAIProvider,
        "gemini": GeminiProvider,
        "anthropic": AnthropicProvider,
        "mock": MockAIProvider,
    }
    factory = registry.get(provider)
    if factory is None:
        raise ValueError(f"Unsupported AI provider: {provider}")
    if provider == "mock" or not settings.ai_api_key:
        return MockAIProvider()
    return factory(api_key=settings.ai_api_key, model=settings.ai_model)
