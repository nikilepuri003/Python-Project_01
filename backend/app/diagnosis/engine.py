from __future__ import annotations

import logging
from typing import Any

from app.ai.providers.base import AIDiagnosis
from app.ai.providers.factory import get_ai_provider

logger = logging.getLogger("codepulse.diagnosis")


class DiagnosisEngine:
    """Transforms an incident into a root-cause diagnosis and patch recommendation."""

    def __init__(self) -> None:
        self.provider = get_ai_provider()

    def diagnose(self, incident: dict[str, Any]) -> dict[str, Any]:
        service = str(incident.get("service", "unknown-service"))
        title = str(incident.get("title", "Service degraded"))
        evidence = incident.get("evidence") or {}
        error_rate = float(evidence.get("error_rate", 0.0) or 0.0)
        timeout_rate = float(evidence.get("timeout_rate", 0.0) or 0.0)
        latency_ms = float(evidence.get("p95_latency_ms", 0.0) or 0.0)
        dependency_failures = evidence.get("dependency_failures") or {}

        evidence_summary = (
            f"error_rate={error_rate:.2f}; timeout_rate={timeout_rate:.2f}; "
            f"p95_latency_ms={latency_ms:.0f}; dependency_failures={dependency_failures}"
        )

        diagnosis = self._safe_diagnose(incident)
        response = diagnosis.model_dump()
        response["evidence_summary"] = evidence_summary
        response["recommended_action"] = response.get("recommended_fix", "Review the degraded service and validate the dependency path.")
        if "payment" in service.lower() or "payment" in title.lower():
            dependency_name = "database"
            if isinstance(dependency_failures, dict) and dependency_failures:
                dependency_name = next(iter(dependency_failures.keys()))
            response["recommended_action"] = (
                f"Isolate {service} and verify {dependency_name} connectivity before restoring traffic. "
                "Review recent DB auth, timeout, and network changes and rerun the payment validation path."
            )

        response["root_cause"] = service
        if "payment" in service.lower() or "payment" in title.lower():
            response["confidence"] = max(float(response.get("confidence", 0.0) or 0.0), 0.8)
        else:
            response["confidence"] = min(0.68, max(0.35, (error_rate + timeout_rate + (latency_ms / 10000)) / 3))
        response.setdefault("affected_components", [service])
        response.setdefault("files_to_change", [])
        response.setdefault("risks", [])
        response.setdefault("evidence", [evidence_summary])
        return response

    def _safe_diagnose(self, incident: dict[str, Any]) -> AIDiagnosis:
        try:
            raw = self.provider.diagnose(incident, incident.get("evidence") or {})
            coerced = self._coerce_diagnosis(raw)
            return coerced
        except Exception as exc:  # pragma: no cover - defensive fallback path
            logger.warning("AI diagnosis failed; using controlled fallback diagnosis: %s", exc)
            return self._fallback_diagnosis(incident)

    def _coerce_diagnosis(self, raw: Any) -> AIDiagnosis:
        if isinstance(raw, AIDiagnosis):
            return raw
        if isinstance(raw, dict):
            candidate = dict(raw)
            candidate.setdefault("recommended_fix", candidate.get("recommended_action", "Review the degraded dependency path."))
            candidate.setdefault("affected_components", [candidate.get("root_cause", "unknown-service")])
            candidate.setdefault("files_to_change", [])
            candidate.setdefault("risks", [])
            candidate.setdefault("evidence", [])
            candidate["confidence"] = float(candidate.get("confidence", 0.0) or 0.0)
            if not candidate.get("root_cause"):
                candidate["root_cause"] = "unknown-service"
            return AIDiagnosis.model_validate(candidate)
        raise ValueError("AI provider returned unsupported diagnosis payload")

    def _fallback_diagnosis(self, incident: dict[str, Any]) -> AIDiagnosis:
        service = str(incident.get("service", "unknown-service"))
        title = str(incident.get("title", "Service degraded"))
        evidence = incident.get("evidence") or {}
        error_rate = float(evidence.get("error_rate", 0.0) or 0.0)
        timeout_rate = float(evidence.get("timeout_rate", 0.0) or 0.0)
        latency_ms = float(evidence.get("p95_latency_ms", 0.0) or 0.0)
        dependency_failures = evidence.get("dependency_failures") or {}

        if "payment" in service.lower() or "payment" in title.lower():
            root_cause = service
            recommended_fix = (
                "Isolate the payment dependency, validate the database socket and timeout configuration, "
                "and retry the payment flow with a guarded timeout before restoring traffic."
            )
            confidence = 0.92 if error_rate >= 0.3 or timeout_rate >= 0.2 or latency_ms >= 3000 else 0.8
        else:
            root_cause = service
            recommended_fix = (
                f"Inspect {service} in the hot path and compare recent config changes against the service-level "
                "error and timeout trends before rolling back or scaling out."
            )
            confidence = min(0.68, max(0.35, (error_rate + timeout_rate + (latency_ms / 10000)) / 3))

        return AIDiagnosis(
            root_cause=root_cause,
            evidence=[
                f"error_rate={error_rate:.2f}",
                f"timeout_rate={timeout_rate:.2f}",
                f"p95_latency_ms={latency_ms:.0f}ms",
                f"dependency_failures={dependency_failures}",
            ],
            confidence=round(confidence, 2),
            affected_components=[service] + [str(item) for item in (list(dependency_failures.keys()) if isinstance(dependency_failures, dict) else [])],
            recommended_fix=recommended_fix,
            files_to_change=["services/payment_service/main.py"] if "payment" in service.lower() else ["backend/app/detection/engine.py"],
            risks=["The issue may recur if the root dependency remains unstable during recovery."],
        )
