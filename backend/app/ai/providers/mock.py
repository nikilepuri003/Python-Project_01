from __future__ import annotations

from typing import Any

from app.ai.providers.base import AIProvider, AIDiagnosis


class MockAIProvider(AIProvider):
    """Fallback provider used when no real AI provider is configured."""

    def diagnose(self, incident: dict[str, Any], evidence: dict[str, Any] | None = None) -> AIDiagnosis:
        service = str(incident.get("service") or incident.get("title") or "unknown-service")
        evidence_payload = evidence or incident.get("evidence") or {}
        error_rate = float(evidence_payload.get("error_rate", 0.0) or 0.0)
        timeout_rate = float(evidence_payload.get("timeout_rate", 0.0) or 0.0)
        p95_latency_ms = float(evidence_payload.get("p95_latency_ms", 0.0) or 0.0)
        dependency_failures = evidence_payload.get("dependency_failures") or {}

        root_cause = service
        if "payment" in service.lower() or dependency_failures:
            root_cause = service

        confidence = 0.92 if error_rate >= 0.3 or timeout_rate >= 0.2 or p95_latency_ms >= 3000 else 0.74
        affected_components = [service]
        if dependency_failures:
            affected_components.extend(str(name) for name in dependency_failures.keys())

        return AIDiagnosis(
            root_cause=root_cause,
            evidence=[
                f"error_rate={error_rate:.2f}",
                f"timeout_rate={timeout_rate:.2f}",
                f"p95_latency_ms={p95_latency_ms:.0f}ms",
                f"dependency_failures={dependency_failures}",
            ],
            confidence=round(confidence, 2),
            affected_components=affected_components[:5],
            recommended_fix=(
                "Reduce dependency latency, verify the database timeout configuration, "
                "and add a short timeout/retry guard before the payment call is retried."
            ),
            files_to_change=["services/payment_service/main.py", "backend/app/detection/engine.py"],
            risks=["Short-term retries may amplify pressure if the upstream database is already unhealthy."],
        )
