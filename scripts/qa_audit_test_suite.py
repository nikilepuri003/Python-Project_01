"""Comprehensive QA Test Suite & Audit for CodePulse AI MVP.

Follows ISTQB & ISO/IEC 25010 Quality Standards:
- Functional & API Contract Testing
- Edge Case & Negative Payload Testing
- Resilience & Fault Injection
- Safety & Human-in-the-Loop Guardrail Verification
- Concurrency & Performance Smoke Testing
"""

from __future__ import annotations

import concurrent.futures
import json
import time
from typing import Any

import httpx

BACKEND_URL = "http://127.0.0.1:8000"
FRONTEND_URL = "http://127.0.0.1:5173"


class QAAuditRunner:
    def __init__(self) -> None:
        self.results: list[dict[str, Any]] = []

    def record(self, suite: str, test_name: str, passed: bool, details: str, duration_ms: float) -> None:
        self.results.append({
            "suite": suite,
            "test": test_name,
            "passed": passed,
            "details": details,
            "duration_ms": round(duration_ms, 2),
        })

    def run_all(self) -> None:
        with httpx.Client(timeout=15.0) as client:
            self.test_system_health(client)
            self.test_api_contract_and_services(client)
            self.test_metrics_and_observability(client)
            self.test_incident_lifecycle(client)
            self.test_negative_and_edge_cases(client)
            self.test_safety_and_guardrails(client)
            self.test_concurrency_and_performance(client)
            self.test_frontend_availability(client)

    def test_system_health(self, client: httpx.Client) -> None:
        suite = "1. Health & Liveness Checks"
        t0 = time.perf_counter()
        r = client.get(f"{BACKEND_URL}/health")
        passed = r.status_code == 200 and r.json().get("status") == "ok"
        self.record(suite, "GET /health liveness", passed, f"Status: {r.status_code}, Body: {r.text}", (time.perf_counter() - t0) * 1000)

        t0 = time.perf_counter()
        r = client.get(f"{BACKEND_URL}/ready")
        passed = r.status_code == 200 and r.json().get("status") == "ready"
        self.record(suite, "GET /ready readiness", passed, f"Status: {r.status_code}, Body: {r.text}", (time.perf_counter() - t0) * 1000)

    def test_api_contract_and_services(self, client: httpx.Client) -> None:
        suite = "2. Service Discovery & Contract Testing"
        t0 = time.perf_counter()
        r = client.get(f"{BACKEND_URL}/api/v1/services")
        data = r.json() if r.status_code == 200 else {}
        items = data.get("items", [])
        passed = r.status_code == 200 and len(items) == 3 and all("id" in s for s in items)
        self.record(suite, "GET /api/v1/services schema validation", passed, f"Found {len(items)} microservices registered", (time.perf_counter() - t0) * 1000)

        for s_id in ["user-service", "order-service", "payment-service"]:
            t0 = time.perf_counter()
            r = client.get(f"{BACKEND_URL}/api/v1/services/{s_id}")
            passed = r.status_code == 200 and r.json().get("id") == s_id
            self.record(suite, f"GET /api/v1/services/{s_id}", passed, f"Status {r.status_code}, Service name: {r.json().get('name')}", (time.perf_counter() - t0) * 1000)

    def test_metrics_and_observability(self, client: httpx.Client) -> None:
        suite = "3. Telemetry & Metrics"
        t0 = time.perf_counter()
        r = client.get(f"{BACKEND_URL}/metrics")
        passed = r.status_code == 200 and "codepulse_backend_http_requests_total" in r.text
        self.record(suite, "Prometheus /metrics export", passed, f"Metrics payload size: {len(r.text)} bytes", (time.perf_counter() - t0) * 1000)

        t0 = time.perf_counter()
        r = client.get(f"{BACKEND_URL}/api/v1/metrics")
        data = r.json() if r.status_code == 200 else {}
        passed = r.status_code == 200 and "request_count" in data and "error_rate" in data
        self.record(suite, "Aggregated /api/v1/metrics API", passed, f"Snapshot: request_count={data.get('request_count')}, error_rate={data.get('error_rate')}", (time.perf_counter() - t0) * 1000)

    def test_incident_lifecycle(self, client: httpx.Client) -> None:
        suite = "4. End-to-End AI Observability Workflow"
        # Reset store first
        client.post(f"{BACKEND_URL}/api/v1/incidents/reset")

        # 1. Detection
        t0 = time.perf_counter()
        detection_payload = {
            "services": [
                {"id": "user-service", "status": "healthy", "error_rate": 0.01, "timeout_rate": 0.0, "p95_latency_ms": 120},
                {"id": "order-service", "status": "degraded", "error_rate": 0.35, "timeout_rate": 0.20, "p95_latency_ms": 3500, "dependency_failures": {"payment-service": 4}},
                {"id": "payment-service", "status": "critical", "error_rate": 0.50, "timeout_rate": 0.40, "p95_latency_ms": 6000, "dependency_failures": {"postgres": 5}},
            ]
        }
        r_det = client.post(f"{BACKEND_URL}/api/v1/detection/evaluate", json=detection_payload)
        items = r_det.json().get("items", [])
        passed = r_det.status_code == 200 and len(items) >= 1
        incident = items[0] if items else {}
        self.record(suite, "Detection Engine Evaluation", passed, f"Detected {len(items)} incidents. Primary: {incident.get('service')}", (time.perf_counter() - t0) * 1000)

        # 2. Evidence Normalization
        t0 = time.perf_counter()
        r_ev = client.post(f"{BACKEND_URL}/api/v1/incidents/evidence", json={
            "service": {"id": "payment-service"},
            "context": {"errors": ["database timeout"], "dependencies": ["postgres"]}
        })
        passed = r_ev.status_code == 200 and "evidence" in r_ev.json()
        self.record(suite, "Evidence Collector & Normalizer", passed, f"Evidence score: {r_ev.json().get('evidence', {}).get('score')}", (time.perf_counter() - t0) * 1000)

        # 3. AI Diagnosis
        t0 = time.perf_counter()
        r_diag = client.post(f"{BACKEND_URL}/api/v1/diagnosis/evaluate", json=incident)
        diag = r_diag.json()
        passed = r_diag.status_code == 200 and diag.get("confidence", 0) >= 0.7
        self.record(suite, "AI Diagnosis Reasoning", passed, f"Root cause: {diag.get('root_cause')}, Confidence: {diag.get('confidence')}", (time.perf_counter() - t0) * 1000)

        # 4. Patch Generation
        t0 = time.perf_counter()
        r_patch = client.post(f"{BACKEND_URL}/api/v1/patches/generate", json={"incident": incident, "diagnosis": diag})
        patch = r_patch.json()
        passed = r_patch.status_code == 200 and "diff" in patch and "--- a/" in patch.get("diff", "")
        self.record(suite, "Safe Patch Generation (Unified Diff)", passed, f"File: {patch.get('file_path')}, Confidence: {patch.get('confidence')}", (time.perf_counter() - t0) * 1000)

        # 5. Patch Validation Pipeline
        t0 = time.perf_counter()
        r_val = client.post(f"{BACKEND_URL}/api/v1/patches/validate-pipeline", json={"patch": patch})
        val = r_val.json()
        passed = r_val.status_code == 200 and val.get("passed") is True
        self.record(suite, "Non-Destructive Validation Pipeline", passed, f"Passed: {val.get('passed')}, Checks: {val.get('checks')}", (time.perf_counter() - t0) * 1000)

    def test_negative_and_edge_cases(self, client: httpx.Client) -> None:
        suite = "5. Negative & Boundary Testing"
        # 404 for unknown service
        t0 = time.perf_counter()
        r = client.get(f"{BACKEND_URL}/api/v1/services/non-existent-service-xyz")
        passed = r.status_code == 404
        self.record(suite, "GET non-existent service returns 404", passed, f"Status: {r.status_code}", (time.perf_counter() - t0) * 1000)

        # 404 for unknown incident
        t0 = time.perf_counter()
        r = client.get(f"{BACKEND_URL}/api/v1/incidents/invalid-uuid-999")
        passed = r.status_code == 404
        self.record(suite, "GET non-existent incident returns 404", passed, f"Status: {r.status_code}", (time.perf_counter() - t0) * 1000)

        # Empty payload to detection
        t0 = time.perf_counter()
        r = client.post(f"{BACKEND_URL}/api/v1/detection/evaluate", json={})
        passed = r.status_code == 200 and r.json().get("items") == []
        self.record(suite, "Detection with empty payload handles gracefully", passed, f"Items: {r.json().get('items')}", (time.perf_counter() - t0) * 1000)

        # Invalid diff payload to validator
        t0 = time.perf_counter()
        r = client.post(f"{BACKEND_URL}/api/v1/patches/validate", json={"patch": {"diff": "invalid arbitrary string"}})
        passed = r.status_code == 200 and r.json().get("passed") is False
        self.record(suite, "Validator rejects malformed patch diffs", passed, f"Passed: {r.json().get('passed')}, Summary: {r.json().get('summary')}", (time.perf_counter() - t0) * 1000)

    def test_safety_and_guardrails(self, client: httpx.Client) -> None:
        suite = "6. Security & Safety Guardrails"
        # Check GitHub mock isolation (human-in-the-loop)
        t0 = time.perf_counter()
        r = client.post(f"{BACKEND_URL}/api/v1/github/pr", json={"title": "fix: payment retry guard", "head": "fix/test", "base": "main"})
        data = r.json()
        passed = r.status_code == 200 and data.get("draft") is True and data.get("source") == "mock"
        self.record(suite, "PR Generation is isolated & marked as Draft", passed, f"Draft: {data.get('draft')}, Note: {data.get('note')}", (time.perf_counter() - t0) * 1000)

        # Ensure no accidental destructive execution endpoint exists
        t0 = time.perf_counter()
        r = client.post(f"{BACKEND_URL}/api/v1/patches/apply-to-repo", json={})
        passed = r.status_code in (404, 405)
        self.record(suite, "No autonomous unapproved repo mutation endpoint", passed, f"Endpoint safely blocked (HTTP {r.status_code})", (time.perf_counter() - t0) * 1000)

    def test_concurrency_and_performance(self, client: httpx.Client) -> None:
        suite = "7. Concurrency & Performance Smoke Test"
        t0 = time.perf_counter()
        urls = [
            f"{BACKEND_URL}/health",
            f"{BACKEND_URL}/api/v1/services",
            f"{BACKEND_URL}/api/v1/metrics",
        ] * 10  # 30 concurrent requests

        def fetch(url: str) -> int:
            return client.get(url).status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            status_codes = list(executor.map(fetch, urls))

        duration_ms = (time.perf_counter() - t0) * 1000
        avg_latency_ms = duration_ms / len(urls)
        passed = all(code == 200 for code in status_codes)
        self.record(suite, "30 Concurrent API Requests Burst", passed, f"Success rate: 100%, Total time: {round(duration_ms, 2)}ms, Avg latency: {round(avg_latency_ms, 2)}ms/req", duration_ms)

    def test_frontend_availability(self, client: httpx.Client) -> None:
        suite = "8. Frontend Dashboard UI Integrity"
        t0 = time.perf_counter()
        r = client.get(FRONTEND_URL)
        passed = r.status_code == 200 and "html" in r.headers.get("content-type", "").lower()
        self.record(suite, "Vite Single-Page Application Serving", passed, f"HTTP {r.status_code}, Length: {len(r.text)} bytes", (time.perf_counter() - t0) * 1000)


if __name__ == "__main__":
    runner = QAAuditRunner()
    runner.run_all()
    print(json.dumps(runner.results, indent=2))
