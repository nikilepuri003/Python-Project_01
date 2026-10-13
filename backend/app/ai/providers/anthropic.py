from __future__ import annotations

import json
import os
from typing import Any

import httpx

from app.ai.providers.base import AIProvider, AIDiagnosis


class AnthropicProvider(AIProvider):
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or os.getenv("AI_API_KEY", "")
        self.model = model or os.getenv("AI_MODEL", "claude-3-5-sonnet-20241022")

    def diagnose(self, incident: dict[str, Any], evidence: dict[str, Any] | None = None) -> AIDiagnosis:
        if not self.api_key:
            from app.ai.providers.mock import MockAIProvider

            return MockAIProvider().diagnose(incident, evidence)

        response = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": 512,
                "messages": [{
                    "role": "user",
                    "content": (
                        "Return only valid JSON with fields root_cause, evidence, confidence, affected_components, "
                        "recommended_fix, files_to_change, risks. "
                        f"Incident={incident}; Evidence={evidence or incident.get('evidence') or {}}"
                    ),
                }],
            },
            timeout=20.0,
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["content"][0]["text"]
        data = json.loads(content.strip("```json").strip("```"))
        return AIDiagnosis.model_validate(data)
