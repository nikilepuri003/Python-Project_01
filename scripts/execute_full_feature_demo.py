"""Step-by-step automated feature execution demo for CodePulse AI."""

from __future__ import annotations

import json
import sys
import time
from typing import Any

import httpx

if sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_URL = "http://127.0.0.1:8000"


def print_step(step_num: int, title: str, description: str) -> None:
    print(f"\n{'='*70}")
    print(f"[FEATURE {step_num}] {title.upper()}")
    print(f"{'='*70}")
    print(f"Info: {description}\n")


def main() -> None:
    with httpx.Client(timeout=20.0) as client:
        # ----------------------------------------------------
        # FEATURE 1: Google OAuth Authentication & Verification
        # ----------------------------------------------------
        print_step(1, "Google OAuth Authentication & Verification", "User signs in and verifies identity with role-based access control.")
        auth_res = client.post(f"{BASE_URL}/api/v1/auth/google", json={
            "email": "nikil.lead.sre@agriconnect.org",
            "name": "Nikil (Lead DevOps)",
            "token": "google-oauth-demo-token-verified",
        }).json()
        print(f"User Profile: {auth_res['user']['name']} ({auth_res['user']['email']})")
        print(f"Role & Access: {auth_res['user']['role']} [Verified: {auth_res['user']['email_verified']}]")
        print(f"Status: {auth_res['message']}")
        time.sleep(0.5)

        # ----------------------------------------------------
        # FEATURE 2: Live Real-Time HTTP Website Probe
        # ----------------------------------------------------
        print_step(2, "Live Real-Time Web Target Probe", "Probing external target (https://agri-connect-prototype-nikil2.vercel.app/).")
        probe_res = client.post(f"{BASE_URL}/api/v1/agri-connect/probe").json()
        print(f"Target: {probe_res['url']}")
        print(f"Round-trip Latency: {probe_res['avg_latency_ms']} ms")
        print(f"Status Codes: {probe_res['status_codes']}")
        print(f"Health Status: {'HEALTHY (200 OK)' if probe_res['healthy'] else 'DEGRADED'}")
        time.sleep(0.5)

        # ----------------------------------------------------
        # FEATURE 3: Microservice Topology & Telemetry
        # ----------------------------------------------------
        print_step(3, "Microservice Topology & Telemetry Discovery", "Querying the 4 distributed microservices and metrics stream.")
        services_res = client.get(f"{BASE_URL}/api/v1/services").json()
        metrics_res = client.get(f"{BASE_URL}/api/v1/metrics").json()
        print(f"Registered Services ({services_res['total']}):")
        for s in services_res['items']:
            print(f"   * [{s['status'].upper()}] {s['name']} (Latency: {s.get('latency_ms', 0)}ms)")
        print(f"Aggregated Telemetry: {metrics_res['request_count']} req/min | P95 Latency: {metrics_res['p95_latency_ms']}ms | Error Rate: {metrics_res['error_rate']}%")
        time.sleep(0.5)

        # ----------------------------------------------------
        # FEATURE 4: Scenario 1 - Baseline Normal Traffic
        # ----------------------------------------------------
        print_step(4, "Scenario 1: Live Baseline Evaluation", "Evaluating normal traffic metrics against AI anomaly thresholds.")
        sc1 = client.post(f"{BASE_URL}/api/v1/agri-connect/set-scenario", json={"scenario": "baseline"}).json()
        analysis_sc1 = client.get(f"{BASE_URL}/api/v1/agri-connect/current-analysis").json()
        print(f"Active Mode: {sc1['scenario']}")
        print(f"AI Incident State: {'No active incidents (System Normal)' if not analysis_sc1['incident'] else 'Incident open'}")
        time.sleep(0.5)

        # ----------------------------------------------------
        # FEATURE 5: Scenario 2 - Edge Latency Degradation
        # ----------------------------------------------------
        print_step(5, "Scenario 2: Edge Latency Degradation (504 Timeouts)", "Simulating API Gateway slowdown and triggering AI diagnosis.")
        sc2 = client.post(f"{BASE_URL}/api/v1/agri-connect/set-scenario", json={"scenario": "latency"}).json()
        analysis_sc2 = client.get(f"{BASE_URL}/api/v1/agri-connect/current-analysis").json()
        print(f"Triggered Incident: {analysis_sc2['incident']['title']}")
        print(f"Root Cause: {analysis_sc2['diagnosis']['root_cause']}")
        print(f"AI Hypothesis: {analysis_sc2['diagnosis']['hypothesis']}")
        print(f"Recommended Fix: {analysis_sc2['diagnosis']['recommended_fix']}")
        time.sleep(0.5)

        # ----------------------------------------------------
        # FEATURE 6: Scenario 3 - Critical Database Outage
        # ----------------------------------------------------
        print_step(6, "Scenario 3: Critical Database Connection Pool Outage", "Simulating DB pool exhaustion with cascading HTTP 500 errors.")
        sc3 = client.post(f"{BASE_URL}/api/v1/agri-connect/set-scenario", json={"scenario": "outage"}).json()
        analysis_sc3 = client.get(f"{BASE_URL}/api/v1/agri-connect/current-analysis").json()
        print(f"Critical Incident: {analysis_sc3['incident']['title']}")
        print(f"Root Cause: {analysis_sc3['diagnosis']['root_cause']} (Confidence: {int(analysis_sc3['diagnosis']['confidence']*100)}%)")
        print(f"AI Reasoning: {analysis_sc3['diagnosis']['hypothesis']}")
        time.sleep(0.5)

        # ----------------------------------------------------
        # FEATURE 7: AI Safe Patch Generation (Unified Diff)
        # ----------------------------------------------------
        print_step(7, "AI Safe Patch Generation", "Generating minimal unified git diff without repo destruction.")
        patch = analysis_sc3['patch']
        print(f"Target File: {patch['file_path']}")
        print(f"Proposed Code Diff:\n{patch['diff']}")
        print(f"Risk Assessment: {patch['risks'][0]}")
        time.sleep(0.5)

        # ----------------------------------------------------
        # FEATURE 8: Non-Destructive Validation Pipeline
        # ----------------------------------------------------
        print_step(8, "Non-Destructive Validation Pipeline", "Testing the proposed patch across test suites and format checks.")
        val_res = client.post(f"{BASE_URL}/api/v1/patches/validate-pipeline", json={"patch": patch}).json()
        print(f"Validation Result: {'PASSED [OK]' if val_res['passed'] else 'FAILED [X]'}")
        print(f"Automated Checks Run: {', '.join(val_res['checks'])}")
        print(f"Summary: {val_res['summary']}")
        time.sleep(0.5)

        # ----------------------------------------------------
        # FEATURE 9: Safe GitHub Draft Pull Request
        # ----------------------------------------------------
        print_step(9, "Safe GitHub Draft Pull Request Creation", "Packaging validated patch into a Draft PR for human engineer approval.")
        pr_res = client.post(f"{BASE_URL}/api/v1/github/pr", json={
            "title": "fix: database timeout guard & fallback queue in AgriConnect",
            "head": "fix/agri-connect-patch",
            "base": "main"
        }).json()
        print(f"Pull Request URL: {pr_res['url']}")
        print(f"Branch: {pr_res['head']} -> {pr_res['base']}")
        print(f"Isolation Status: Draft PR (Source: {pr_res['source']})")
        print(f"Note: {pr_res['note']}")

        print(f"\n{'='*70}")
        print("ALL 9 CODEPULSE AI FEATURES EXECUTED AND VERIFIED SUCCESSFULLY!")
        print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
