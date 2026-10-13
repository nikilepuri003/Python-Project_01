from __future__ import annotations

import json
import os
from typing import Any

import httpx

from app.ai.providers.base import AIProvider, AIDiagnosis


class GeminiProvider(AIProvider):
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or os.getenv("AI_API_KEY", "")
        self.model = model or os.getenv("AI_MODEL", "gemini-2.5-flash")

    def diagnose(self, incident: dict[str, Any], evidence: dict[str, Any] | None = None) -> AIDiagnosis:
        if not self.api_key:
            from app.ai.providers.mock import MockAIProvider

            return MockAIProvider().diagnose(incident, evidence)

        payload = {
            "contents": [{
                "parts": [{
                    "text": (
                        "Return only valid JSON with fields root_cause, evidence, confidence, "
                        "affected_components, recommended_fix, files_to_change, risks. "
                        f"Incident={incident}; Evidence={evidence or incident.get('evidence') or {}}"
                    )
                }]
            }]
        }
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}",
            json=payload,
            timeout=20.0,
        )
        response.raise_for_status()
        result = response.json()
        text = result["candidates"][0]["content"]["parts"][0]["text"]
        data = json.loads(text.strip("```json").strip("```"))
        return AIDiagnosis.model_validate(data)
