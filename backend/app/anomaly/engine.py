from __future__ import annotations

from typing import Any

import numpy as np


class AnomalyDetector:
    """Detect unusual service behavior using a robust statistical anomaly detector.

    This detector is intentionally supplemental: deterministic rules remain the
    source of truth for incident creation. It highlights potential outliers
    that deserve deeper investigation or evidence scoring.
    """

    def evaluate(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        services = snapshot.get("services", [])
        if not services:
            return []

        rows: list[list[float]] = []
        service_refs: list[dict[str, Any]] = []

        for service in services:
            feature_vector = self._feature_vector(service)
            if feature_vector is None:
                continue
            rows.append(feature_vector)
            service_refs.append(service)

        if len(rows) < 2 or np.allclose(rows, rows[0]):
            return []

        anomalies: list[dict[str, Any]] = []
        data = np.asarray(rows, dtype=float)
        means = np.mean(data, axis=0)
        stds = np.std(data, axis=0)
        stds[stds == 0] = 1.0

        for service, row in zip(service_refs, rows):
            vec = np.asarray(row, dtype=float)
            z_scores = np.abs((vec - means) / stds)
            max_z = float(np.max(z_scores))
            error_rate = float(service.get("error_rate", 0.0) or 0.0)
            timeout_rate = float(service.get("timeout_rate", 0.0) or 0.0)
            p95_latency_ms = float(service.get("p95_latency_ms", 0.0) or 0.0)

            is_anomaly = max_z > 1.2 or error_rate >= 0.1 or timeout_rate >= 0.05 or p95_latency_ms > 3000
            if is_anomaly:
                score = min(1.0, float(0.5 + 0.1 * max_z + 0.2 * error_rate + 0.2 * timeout_rate))
                anomalies.append(
                    {
                        "service": str(service.get("id", "unknown-service")),
                        "is_anomaly": True,
                        "score": round(score, 6),
                        "severity": "high" if score >= 0.75 else "medium",
                        "feature_vector": {
                            "request_count": float(service.get("request_count", 0.0) or 0.0),
                            "error_rate": error_rate,
                            "mean_latency_ms": float(service.get("mean_latency_ms", 0.0) or 0.0),
                            "p95_latency_ms": p95_latency_ms,
                            "timeout_rate": timeout_rate,
                        },
                    }
                )
        return anomalies

    def _feature_vector(self, service: dict[str, Any]) -> list[float] | None:
        request_count = float(service.get("request_count", 0.0) or 0.0)
        error_rate = float(service.get("error_rate", 0.0) or 0.0)
        mean_latency_ms = float(service.get("mean_latency_ms", 0.0) or 0.0)
        p95_latency_ms = float(service.get("p95_latency_ms", 0.0) or 0.0)
        timeout_rate = float(service.get("timeout_rate", 0.0) or 0.0)

        if not any((request_count, error_rate, mean_latency_ms, p95_latency_ms, timeout_rate)):
            return None

        return [request_count, error_rate, mean_latency_ms, p95_latency_ms, timeout_rate]
