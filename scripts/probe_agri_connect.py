"""Observability Probe and CodePulse AI Analysis for External Web Application:
Target: https://agri-connect-prototype-nikil2.vercel.app/
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

CODEPULSE_API = "http://127.0.0.1:8000"
TARGET_URL = "https://agri-connect-prototype-nikil2.vercel.app"


def probe_live_website(url: str) -> dict[str, Any]:
    """Perform benign HTTP observability probe on the target URL."""
    latencies: list[float] = []
    status_codes: list[int] = []
    
    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        for _ in range(3):
            t0 = time.perf_counter()
            try:
                res = client.get(url)
                latencies.append((time.perf_counter() - t0) * 1000)
                status_codes.append(res.status_code)
            except Exception as e:
                latencies.append(10000.0)
                status_codes.append(504)

    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
    success_rate = sum(1 for code in status_codes if code < 400) / len(status_codes)
    error_rate = 1.0 - success_rate

    return {
        "url": url,
        "target_service": "agri-connect-web",
        "avg_latency_ms": round(avg_latency, 2),
        "status_codes": status_codes,
        "error_rate": error_rate,
        "healthy": error_rate == 0.0,
    }


def analyze_with_codepulse(scenario_name: str, telemetry: dict[str, Any]) -> dict[str, Any]:
    """Feed observed or simulated telemetry through CodePulse AI pipeline."""
    payload = {
        "service": {
            "id": telemetry.get("id", "agri-connect-frontend"),
            "name": "AgriConnect Web Portal",
            "status": "healthy" if telemetry.get("healthy") else ("critical" if telemetry.get("error_rate", 0) > 0.3 else "degraded"),
            "latency_ms": telemetry.get("latency_ms", 120),
            "error_rate": telemetry.get("error_rate", 0.0),
            "timeout_rate": telemetry.get("timeout_rate", 0.0),
            "dependencies": ["vercel-edge", "api-gateway", "database"],
            "healthy": telemetry.get("healthy", True),
        },
        "context": {
            "trace_id": f"agri-connect-{scenario_name.lower().replace(' ', '-')}-trace",
            "errors": telemetry.get("errors", []),
            "recent_changes": telemetry.get("recent_changes", ["new Vercel deployment v1.2"]),
            "dependencies": ["vercel-edge", "api-gateway", "database"],
            "dependency_health": telemetry.get("dependency_health", {"vercel-edge": "healthy"}),
            "metrics_snapshot": {
                "request_count": telemetry.get("request_count", 850),
                "error_rate": telemetry.get("error_rate", 0.0),
                "p95_latency_ms": telemetry.get("latency_ms", 120),
                "timeout_rate": telemetry.get("timeout_rate", 0.0),
            },
        },
    }

    with httpx.Client(timeout=30.0) as client:
        detection = client.post(f"{CODEPULSE_API}/api/v1/detection/evaluate", json=payload).json()
        diagnosis = client.post(f"{CODEPULSE_API}/api/v1/diagnosis/evaluate", json=payload).json()
        patch = client.post(f"{CODEPULSE_API}/api/v1/patches/generate", json={"incident": payload, "diagnosis": diagnosis}).json()
        validation = client.post(f"{CODEPULSE_API}/api/v1/patches/validate-pipeline", json={"patch": patch}).json()
        pr = client.post(f"{CODEPULSE_API}/api/v1/github/pr", json={"title": f"fix: {scenario_name} in AgriConnect Web", "head": "fix/agri-connect-patch", "base": "main"}).json()

    return {
        "scenario": scenario_name,
        "input_telemetry": telemetry,
        "detection": detection,
        "ai_diagnosis": {
            "root_cause": diagnosis.get("root_cause"),
            "confidence": diagnosis.get("confidence"),
            "recommended_fix": diagnosis.get("recommended_fix"),
        },
        "generated_patch_diff": patch.get("diff"),
        "validation_outcome": validation,
        "draft_pr": pr,
    }


def main() -> None:
    # 1. Real live probe
    live_probe = probe_live_website(TARGET_URL)

    # Scenario A: Live Normal Traffic (Observed metrics)
    res_a = analyze_with_codepulse("Live Baseline Traffic", {
        "id": "agri-connect-web",
        "healthy": live_probe["healthy"],
        "latency_ms": live_probe["avg_latency_ms"],
        "error_rate": live_probe["error_rate"],
        "timeout_rate": 0.0,
        "request_count": 920,
        "errors": [],
        "dependency_health": {"vercel-edge": "healthy", "api-gateway": "healthy"},
    })

    # Scenario B: Simulated Edge Latency Spike & Degraded Gateway
    res_b = analyze_with_codepulse("Edge Latency Degradation", {
        "id": "agri-connect-web",
        "healthy": False,
        "latency_ms": 2850,
        "error_rate": 0.08,
        "timeout_rate": 0.05,
        "request_count": 1400,
        "errors": ["upstream gateway timeout: 504", "slow render bundle chunk"],
        "recent_changes": ["updated SSR data-fetch hook"],
        "dependency_health": {"vercel-edge": "healthy", "api-gateway": "degraded"},
    })

    # Scenario C: Simulated Critical Backend Outage (DB & API 500s)
    res_c = analyze_with_codepulse("Critical Backend Outage", {
        "id": "agri-connect-web",
        "healthy": False,
        "latency_ms": 5200,
        "error_rate": 0.38,
        "timeout_rate": 0.25,
        "request_count": 2100,
        "errors": ["database connection pool exhausted", "failed to fetch /api/v1/crops", "HTTP 500 internal server error"],
        "recent_changes": ["marketplace schema migration"],
        "dependency_health": {"api-gateway": "critical", "database": "critical"},
    })

    output = {
        "target_url": TARGET_URL,
        "live_probe_results": live_probe,
        "scenario_comparisons": [res_a, res_b, res_c],
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
