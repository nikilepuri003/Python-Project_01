from __future__ import annotations

import uuid
from typing import Any

from app.incidents.evidence import IncidentNormalizer


class DetectionEngine:
    """Deterministic rules for converting service health snapshots into incidents."""

    def evaluate(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        incidents: list[dict[str, Any]] = []
        for service in snapshot.get("services", []):
            incident = self._evaluate_service(service)
            if incident is not None:
                incidents.append(incident)
        return incidents

    def _evaluate_service(self, service: dict[str, Any]) -> dict[str, Any] | None:
        service_id = str(service.get("id", "unknown-service"))
        status = str(service.get("status", "healthy")).lower()
        error_rate = float(service.get("error_rate", 0.0) or 0.0)
        timeout_rate = float(service.get("timeout_rate", 0.0) or 0.0)
        latency_ms = float(service.get("p95_latency_ms", 0.0) or 0.0)
        dependency_failures = service.get("dependency_failures") or {}

        dependency_count = 0
        if isinstance(dependency_failures, dict):
            dependency_count = sum(int(count) for count in dependency_failures.values())
        elif isinstance(dependency_failures, list):
            dependency_count = len(dependency_failures)

        if status == "healthy" and error_rate < 0.3 and timeout_rate < 0.2 and latency_ms < 2500 and dependency_count == 0:
            return None

        if service_id == "order-service" and isinstance(dependency_failures, dict) and "payment-service" in dependency_failures:
            if error_rate < 0.4 and timeout_rate < 0.35:
                return None

        if "payment" in service_id and (error_rate >= 0.3 or timeout_rate >= 0.2 or latency_ms >= 3000 or dependency_count >= 2):
            return self._build_incident(service_id, "Payment service degraded", "high", service)

        if dependency_count >= 3 or error_rate >= 0.25 or timeout_rate >= 0.2 or latency_ms >= 2500:
            return self._build_incident(service_id, self._service_title(service_id), "medium", service)

        return None

    def _build_incident(
        self,
        service_id: str,
        title: str,
        severity: str,
        service: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = IncidentNormalizer().normalize(
            {
                "id": str(uuid.uuid4()),
                "service": service_id,
                "title": title,
                "severity": severity,
                "status": "DETECTED",
                "summary": self._summarize(service),
                "evidence": {
                    "error_rate": float(service.get("error_rate", 0.0) or 0.0),
                    "timeout_rate": float(service.get("timeout_rate", 0.0) or 0.0),
                    "p95_latency_ms": float(service.get("p95_latency_ms", 0.0) or 0.0),
                    "dependency_failures": service.get("dependency_failures") or {},
                    "logs": service.get("logs") or [],
                    "trace_ids": service.get("trace_ids") or [],
                    "dependencies": service.get("dependencies") or [],
                    "recent_changes": service.get("recent_changes") or [],
                },
                "created_at": "2026-10-02T00:00:00Z",
            }
        )
        return normalized

    def _service_title(self, service_id: str) -> str:
        return service_id.replace("-", " ").title() + " degraded"

    def _summarize(self, service: dict[str, Any]) -> str:
        error_rate = float(service.get("error_rate", 0.0) or 0.0)
        timeout_rate = float(service.get("timeout_rate", 0.0) or 0.0)
        latency_ms = float(service.get("p95_latency_ms", 0.0) or 0.0)
        dependency_failures = service.get("dependency_failures") or {}

        detail_parts = [
            f"error_rate={error_rate:.2f}",
            f"timeout_rate={timeout_rate:.2f}",
            f"p95_latency_ms={latency_ms:.0f}",
        ]
        if dependency_failures:
            detail_parts.append(f"dependency_failures={dependency_failures}")
        return "; ".join(detail_parts)
