from __future__ import annotations

import os
from typing import Any

from app.ai.providers.anthropic import AnthropicProvider
from app.ai.providers.base import AIProvider
from app.ai.providers.gemini import GeminiProvider
from app.ai.providers.mock import MockAIProvider
from app.ai.providers.openai import OpenAIProvider


def get_ai_provider(provider_name: str | None = None) -> AIProvider:
    provider = (provider_name or os.getenv("AI_PROVIDER") or "mock").lower()
    registry: dict[str, Any] = {
        "openai": OpenAIProvider,
        "gemini": GeminiProvider,
        "anthropic": AnthropicProvider,
        "mock": MockAIProvider,
    }
    factory = registry.get(provider, MockAIProvider)
    return factory()
