"""Create a demo incident payload for the CodePulse detection flow."""

from __future__ import annotations

import argparse
import json

import httpx


def build_payload(mode: str) -> dict[str, object]:
    failure_map = {
        "healthy": {"status": "healthy", "error_rate": 0.01, "latency_ms": 110, "timeout_rate": 0.0},
        "latency": {"status": "degraded", "error_rate": 0.08, "latency_ms": 2800, "timeout_rate": 0.04},
        "database_timeout": {"status": "critical", "error_rate": 0.31, "latency_ms": 5200, "timeout_rate": 0.29},
        "unavailable": {"status": "critical", "error_rate": 0.42, "latency_ms": 0, "timeout_rate": 0.0},
    }
    details = failure_map.get(mode, failure_map["database_timeout"])
    return {
        "service": {
            "id": "payment-service",
            "name": "Payment Service",
            **details,
            "healthy": details["status"] == "healthy",
            "dependencies": ["postgres"],
        },
        "context": {
            "trace_id": "demo-failure-mode",
            "errors": [f"{mode} detected"],
            "recent_changes": ["dependency retry change"],
            "dependencies": ["postgres"],
            "dependency_health": {"postgres": "degraded"},
            "metrics_snapshot": {
                "request_count": 1300,
                "error_rate": details["error_rate"],
                "p95_latency_ms": details["latency_ms"],
                "timeout_rate": details["timeout_rate"],
            },
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a demo payment-service incident payload.")
    parser.add_argument("--mode", default="database_timeout", choices=["healthy", "latency", "database_timeout", "unavailable"])
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--apply", action="store_true", help="Send the generated payload to the backend detection endpoint.")
    args = parser.parse_args()

    payload = build_payload(args.mode)
    if args.apply:
        with httpx.Client() as client:
            response = client.post(f"{args.base_url}/api/v1/detection/evaluate", json=payload, timeout=30.0)
            response.raise_for_status()
            print(json.dumps(response.json(), indent=2))
    else:
        print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
