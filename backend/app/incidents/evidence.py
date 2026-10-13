from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class IncidentEvidenceCollector:
    """Collect structured evidence for a service incident."""

    def collect(self, service: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        service = service or {}
        context = context or {}

        error_rate = float(service.get("error_rate", context.get("error_rate", 0.0)) or 0.0)
        timeout_rate = float(service.get("timeout_rate", context.get("timeout_rate", 0.0)) or 0.0)
        p95_latency_ms = float(service.get("p95_latency_ms", context.get("p95_latency_ms", 0.0)) or 0.0)
        dependency_failures = service.get("dependency_failures") or context.get("dependency_failures") or {}
        logs = service.get("logs") or context.get("logs") or []
        trace_ids = service.get("trace_ids") or context.get("trace_ids") or []
        dependencies = service.get("dependencies") or context.get("dependencies") or []
        recent_changes = service.get("recent_changes") or context.get("recent_changes") or []

        error_correlation = min(max(error_rate / 0.5, 0.0), 1.0) if error_rate > 0 else 0.0
        latency_correlation = min(max(p95_latency_ms / 10000.0, 0.0), 1.0) if p95_latency_ms > 0 else 0.0
        trace_dependency_match = 1.0 if dependency_failures and trace_ids else 0.0
        log_exception_match = 1.0 if any("exception" in str(entry).lower() for entry in logs) else 0.0
        recent_change_match = 1.0 if recent_changes else 0.0

        score = (
            0.30 * error_correlation
            + 0.25 * latency_correlation
            + 0.20 * trace_dependency_match
            + 0.15 * log_exception_match
            + 0.10 * recent_change_match
        )

        return {
            "error_rate": round(error_rate, 4),
            "timeout_rate": round(timeout_rate, 4),
            "p95_latency_ms": round(p95_latency_ms, 2),
            "dependency_failures": dependency_failures,
            "logs": list(logs),
            "trace_ids": list(trace_ids),
            "dependencies": list(dependencies),
            "recent_changes": list(recent_changes),
            "error_correlation": round(error_correlation, 4),
            "latency_correlation": round(latency_correlation, 4),
            "trace_dependency_match": round(trace_dependency_match, 4),
            "log_exception_match": round(log_exception_match, 4),
            "recent_change_match": round(recent_change_match, 4),
            "score": round(score, 4),
        }


class IncidentNormalizer:
    """Normalize raw incident payloads into a consistent internal model."""

    def normalize(self, incident: dict[str, Any]) -> dict[str, Any]:
        incident = dict(incident or {})
        service = str(incident.get("service") or incident.get("service_id") or "unknown-service")
        title = str(incident.get("title") or f"{service.replace('-', ' ').title()} degraded")
        severity = str(incident.get("severity") or "medium").lower()
        severity = severity if severity in {"low", "medium", "high", "critical"} else "medium"
        status = str(incident.get("status") or "DETECTED").lower()
        status_map = {
            "detected": "open",
            "open": "open",
            "investigating": "investigating",
            "diagnosed": "diagnosed",
            "patch_generated": "patch_generated",
            "validating": "validating",
            "validated": "validated",
            "pr_created": "pr_created",
            "resolved": "resolved",
            "failed": "failed",
        }
        status = status_map.get(status, "open")

        evidence = incident.get("evidence") or {}
        if not isinstance(evidence, dict):
            evidence = {}

        normalized_evidence = {
            "error_rate": float(evidence.get("error_rate", 0.0) or 0.0),
            "timeout_rate": float(evidence.get("timeout_rate", 0.0) or 0.0),
            "p95_latency_ms": float(evidence.get("p95_latency_ms", 0.0) or 0.0),
            "dependency_failures": evidence.get("dependency_failures") or {},
            "logs": list(evidence.get("logs") or []),
            "trace_ids": list(evidence.get("trace_ids") or []),
            "dependencies": list(evidence.get("dependencies") or []),
            "recent_changes": list(evidence.get("recent_changes") or []),
            "score": float(evidence.get("score", 0.0) or 0.0),
        }

        if normalized_evidence["score"] == 0.0:
            normalized_evidence["score"] = round(
                (
                    0.30 * min(max(normalized_evidence["error_rate"] / 0.5, 0.0), 1.0)
                    + 0.25 * min(max(normalized_evidence["p95_latency_ms"] / 10000.0, 0.0), 1.0)
                    + 0.20 * (1.0 if normalized_evidence["dependency_failures"] and normalized_evidence["trace_ids"] else 0.0)
                    + 0.15 * (1.0 if any("exception" in str(entry).lower() for entry in normalized_evidence["logs"]) else 0.0)
                    + 0.10 * (1.0 if normalized_evidence["recent_changes"] else 0.0)
                ),
                4,
            )

        normalized = {
            "id": str(incident.get("id") or incident.get("incident_id") or self._generate_id()),
            "service": service,
            "title": title,
            "severity": severity,
            "status": status,
            "summary": str(incident.get("summary") or self._build_summary(normalized_evidence)),
            "evidence": normalized_evidence,
            "created_at": incident.get("created_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        for key in ("root_cause", "root_cause_summary", "confidence", "incident_id", "error_rate", "latency_p95"):
            if key in incident:
                normalized[key] = incident[key]

        return normalized

    def _generate_id(self) -> str:
        import uuid

        return str(uuid.uuid4())

    def _build_summary(self, evidence: dict[str, Any]) -> str:
        return (
            f"error_rate={evidence.get('error_rate', 0.0):.2f}; "
            f"timeout_rate={evidence.get('timeout_rate', 0.0):.2f}; "
            f"p95_latency_ms={evidence.get('p95_latency_ms', 0.0):.0f}; "
            f"dependency_failures={evidence.get('dependency_failures') or {}}"
        )
