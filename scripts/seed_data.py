"""Seed the demo incident flow against the local backend API."""

from __future__ import annotations

import argparse
import json
from typing import Any

import httpx


def build_demo_payload() -> dict[str, Any]:
    return {
        "service": {
            "id": "payment-service",
            "name": "Payment Service",
            "status": "critical",
            "latency_ms": 4200,
            "error_rate": 0.27,
            "timeout_rate": 0.18,
            "dependencies": ["postgres"],
            "healthy": False,
        },
        "context": {
            "trace_id": "demo-payment-incident-001",
            "errors": ["database timeout", "payment request timed out"],
            "recent_changes": ["db connection pool increase", "new retry policy"],
            "dependencies": ["postgres"],
            "dependency_health": {"postgres": "degraded"},
            "metrics_snapshot": {
                "request_count": 1200,
                "error_rate": 0.27,
                "p95_latency_ms": 4200,
                "timeout_rate": 0.18,
            },
        },
    }


def post_json(client: httpx.Client, base_url: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post(f"{base_url}{path}", json=payload, timeout=30.0)
    response.raise_for_status()
    return response.json()


def get_json(client: httpx.Client, base_url: str, path: str) -> dict[str, Any]:
    response = client.get(f"{base_url}{path}", timeout=30.0)
    response.raise_for_status()
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the CodePulse demo incident lifecycle.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Backend base URL")
    args = parser.parse_args()

    payload = build_demo_payload()
    with httpx.Client() as client:
        detection = post_json(client, args.base_url, "/api/v1/detection/evaluate", payload)
        evidence = post_json(client, args.base_url, "/api/v1/incidents/evidence", payload)
        anomaly = post_json(client, args.base_url, "/api/v1/anomaly/evaluate", payload)
        incidents = get_json(client, args.base_url, "/api/v1/incidents")
        diagnosis = post_json(client, args.base_url, "/api/v1/diagnosis/evaluate", detection["items"][0] if detection.get("items") else payload)
        patch = post_json(client, args.base_url, "/api/v1/patches/generate", {"incident": detection["items"][0] if detection.get("items") else payload, "diagnosis": diagnosis})
        validation = post_json(client, args.base_url, "/api/v1/patches/validate-pipeline", {"patch": patch})
        branch = post_json(client, args.base_url, "/api/v1/github/branch", {"branch_name": "fix/codepulse-demo-incident"})
        commit = post_json(client, args.base_url, "/api/v1/github/commit", {"branch_name": "fix/codepulse-demo-incident", "message": "fix: handle payment-service timeout"})
        pr = post_json(client, args.base_url, "/api/v1/github/pr", {"title": "fix: payment-service timeout", "head": "fix/codepulse-demo-incident", "base": "main"})

    summary = {
        "detection": detection,
        "evidence": evidence,
        "anomaly": anomaly,
        "incidents": incidents,
        "diagnosis": diagnosis,
        "patch": patch,
        "validation": validation,
        "github": {"branch": branch, "commit": commit, "pr": pr},
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

