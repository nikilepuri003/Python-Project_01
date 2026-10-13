from __future__ import annotations

import json
import os
from typing import Any

import httpx

from app.ai.providers.base import AIProvider, AIDiagnosis


class OpenAIProvider(AIProvider):
    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None) -> None:
        self.api_key = api_key or os.getenv("AI_API_KEY", "")
        self.model = model or os.getenv("AI_MODEL", "gpt-4o-mini")
        self.base_url = base_url or "https://api.openai.com/v1"

    def diagnose(self, incident: dict[str, Any], evidence: dict[str, Any] | None = None) -> AIDiagnosis:
        if not self.api_key:
            from app.ai.providers.mock import MockAIProvider

            return MockAIProvider().diagnose(incident, evidence)

        prompt = self._build_prompt(incident, evidence)
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
            },
            timeout=20.0,
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        if isinstance(content, str):
            return AIDiagnosis.model_validate(json.loads(content))
        return AIDiagnosis.model_validate(content)

    def _build_prompt(self, incident: dict[str, Any], evidence: dict[str, Any] | None) -> str:
        evidence_payload = evidence or incident.get("evidence") or {}
        return (
            "You are an incident-diagnosis assistant. Return only valid JSON matching the schema: "
            "{root_cause, evidence: [string], confidence: number, affected_components: [string], "
            "recommended_fix: string, files_to_change: [string], risks: [string]}. "
            f"Incident: {incident}. Evidence: {evidence_payload}"
        )
