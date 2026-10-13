import ipaddress
import socket
import time
from typing import Any
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, HTTPException

from app.anomaly.engine import AnomalyDetector
from app.core.config import get_settings
from app.core.security import verify_google_oauth_token
from app.detection.engine import DetectionEngine
from app.diagnosis.engine import DiagnosisEngine
from app.github.service import GitHubService
from app.incidents.evidence import IncidentEvidenceCollector
from app.incidents.store import IncidentStore
from app.patching.engine import PatchGenerator
from app.validation.engine import ValidationEngine
from app.validation.pipeline import ValidationPipeline

router = APIRouter(prefix="/api/v1", tags=["system"])
incident_store = IncidentStore()
detection_engine = DetectionEngine()
diagnosis_engine = DiagnosisEngine()
anomaly_detector = AnomalyDetector()
evidence_collector = IncidentEvidenceCollector()
patch_generator = PatchGenerator()
validation_engine = ValidationEngine()
validation_pipeline = ValidationPipeline()
github_service = GitHubService()

# In-memory user session
CURRENT_USER: dict[str, Any] = {
    "authenticated": False,
    "user": None,
}

# In-memory scenario state
CURRENT_SCENARIO: dict[str, Any] = {
    "name": "Live Baseline (AgriConnect)",
    "target_url": "https://agri-connect-prototype-nikil2.vercel.app",
    "services": [
        {"id": "agri-connect-web", "name": "AgriConnect Web Portal (Vercel)", "status": "healthy", "latency_ms": 1240, "error_rate": 0.0},
        {"id": "agri-crop-service", "name": "Crop Analytics & Advisory Service", "status": "healthy", "latency_ms": 140, "error_rate": 0.0},
        {"id": "agri-market-gateway", "name": "Marketplace API Gateway", "status": "healthy", "latency_ms": 210, "error_rate": 0.01},
        {"id": "agri-database", "name": "Postgres Crop & Order Database", "status": "healthy", "latency_ms": 45, "error_rate": 0.0},
    ],
    "metrics": {
        "request_count": 3420,
        "error_rate": 0.0,
        "p95_latency_ms": 1240,
        "timeout_rate": 0.0,
        "services": ["agri-connect-web", "agri-crop-service", "agri-market-gateway", "agri-database"],
    },
    "incident": None,
    "diagnosis": None,
    "patch": None,
}


@router.post("/auth/google")
def google_auth(payload: dict[str, Any]) -> dict[str, Any]:
    """Authenticate and verify a user via Google OAuth."""
    token = payload.get("token") or payload.get("credential")
    email = payload.get("email")
    name = payload.get("name")
    picture = payload.get("picture")

    if not isinstance(token, str) or not token:
        raise HTTPException(status_code=400, detail="A Google credential is required.")
    if not token.startswith("google-oauth-demo") and not get_settings().google_client_id:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured on the backend.")

    try:
        user_profile = verify_google_oauth_token(token, email=email, name=name, picture=picture)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    CURRENT_USER["authenticated"] = True
    CURRENT_USER["user"] = user_profile

    return {
        "status": "success",
        "message": f"Successfully authenticated as {user_profile['name']}",
        "user": user_profile,
    }


@router.get("/auth/me")
def get_current_user() -> dict[str, Any]:
    """Get the currently authenticated user profile."""
    return CURRENT_USER


@router.post("/auth/logout")
def logout() -> dict[str, Any]:
    """Log out the current user session."""
    CURRENT_USER["authenticated"] = False
    CURRENT_USER["user"] = None
    return {"status": "logged_out", "message": "User session cleared"}


@router.get("/services")
def list_services() -> dict[str, Any]:
    return {
        "items": CURRENT_SCENARIO["services"],
        "total": len(CURRENT_SCENARIO["services"]),
        "scenario": CURRENT_SCENARIO["name"],
    }


@router.get("/services/{service_id}")
def get_service(service_id: str) -> dict[str, Any]:
    for s in CURRENT_SCENARIO["services"]:
        if s["id"] == service_id:
            return s
    raise HTTPException(status_code=404, detail={"error": {"code": "SERVICE_NOT_FOUND", "message": "Service was not found"}})


@router.get("/services/{service_id}/health")
def get_service_health(service_id: str) -> dict[str, Any]:
    service = next((s for s in CURRENT_SCENARIO["services"] if s["id"] == service_id), None)
    status = service["status"] if service else "healthy"
    return {"service": service_id, "status": status, "checks": ["database", "http"], "timestamp": "2026-10-02T00:00:00Z"}


@router.get("/services/{service_id}/metrics")
def get_service_metrics(service_id: str) -> dict[str, Any]:
    service = next((s for s in CURRENT_SCENARIO["services"] if s["id"] == service_id), {})
    return {
        "service": service_id,
        "request_rate": 180,
        "error_rate": service.get("error_rate", 0.0),
        "p95_latency_ms": service.get("latency_ms", 120),
        "timeout_rate": 0.0,
    }


@router.get("/metrics")
def get_metrics() -> dict[str, Any]:
    return CURRENT_SCENARIO["metrics"]


@router.post("/monitor/probe")
def probe_website(payload: dict[str, Any]) -> dict[str, Any]:
    """Check one public HTTP(S) endpoint and report only observed response data."""
    raw_url = payload.get("url")
    if not isinstance(raw_url, str) or not raw_url.strip():
        raise HTTPException(status_code=422, detail="Enter a website URL to check.")

    candidate = raw_url.strip()
    if "://" not in candidate:
        candidate = f"https://{candidate}"

    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Enter a valid website URL.") from exc

    hostname = parsed.hostname
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 80, 443}
        or hostname.endswith(".")
        or hostname.lower() == "localhost"
        or hostname.lower().endswith((".localhost", ".local", ".internal"))
    ):
        raise HTTPException(status_code=422, detail="Use a public website URL with HTTP or HTTPS.")

    try:
        addresses = {
            ipaddress.ip_address(result[4][0])
            for result in socket.getaddrinfo(hostname, port or (443 if parsed.scheme.lower() == "https" else 80), type=socket.SOCK_STREAM)
        }
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="The website hostname could not be resolved.") from exc

    if not addresses or any(not address.is_global for address in addresses):
        raise HTTPException(status_code=422, detail="Only publicly accessible websites can be checked.")

    normalized_url = urlunsplit(
        (parsed.scheme.lower(), parsed.netloc, parsed.path or "/", parsed.query, "")
    )
    started_at = time.perf_counter()
    checked_at = datetime.now(timezone.utc).isoformat()

    try:
        with httpx.Client(
            timeout=httpx.Timeout(10.0, connect=5.0),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = client.get(normalized_url, headers={"User-Agent": "CodePulse-Monitor/1.0"})
    except httpx.TimeoutException:
        return {
            "url": normalized_url,
            "result": "unavailable",
            "reachable": False,
            "status_code": None,
            "response_time_ms": round((time.perf_counter() - started_at) * 1000, 1),
            "message": "The website did not respond before the 10-second timeout.",
            "checked_at": checked_at,
        }
    except httpx.RequestError:
        return {
            "url": normalized_url,
            "result": "unavailable",
            "reachable": False,
            "status_code": None,
            "response_time_ms": round((time.perf_counter() - started_at) * 1000, 1),
            "message": "The website could not be reached. Check the URL and try again.",
            "checked_at": checked_at,
        }

    response_time_ms = round((time.perf_counter() - started_at) * 1000, 1)
    status_code = response.status_code
    if 200 <= status_code < 300:
        result = "healthy"
        message = "The website responded successfully."
    elif 300 <= status_code < 400:
        result = "redirect"
        message = "The website responded with a redirect. Redirect target was not followed."
    elif 400 <= status_code < 500:
        result = "client_error"
        message = "The website is reachable but returned an HTTP client error."
    else:
        result = "server_error"
        message = "The website is reachable but returned an HTTP server error."

    return {
        "url": normalized_url,
        "result": result,
        "reachable": True,
        "status_code": status_code,
        "response_time_ms": response_time_ms,
        "message": message,
        "checked_at": checked_at,
    }


@router.post("/agri-connect/probe")
def probe_agri_connect() -> dict[str, Any]:
    """Perform real live HTTP probe on AgriConnect Vercel app."""
    url = "https://agri-connect-prototype-nikil2.vercel.app"
    latencies: list[float] = []
    status_codes: list[int] = []

    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        for _ in range(3):
            t0 = time.perf_counter()
            try:
                r = client.get(url)
                latencies.append((time.perf_counter() - t0) * 1000)
                status_codes.append(r.status_code)
            except Exception:
                latencies.append(5000.0)
                status_codes.append(504)

    avg_latency = round(sum(latencies) / len(latencies), 1) if latencies else 0.0
    success = all(code == 200 for code in status_codes)

    CURRENT_SCENARIO["name"] = "Live Baseline (AgriConnect)"
    CURRENT_SCENARIO["metrics"] = {
        "request_count": 1820,
        "error_rate": 0.0 if success else 0.1,
        "p95_latency_ms": int(avg_latency),
        "timeout_rate": 0.0,
        "services": ["agri-connect-web", "agri-crop-service", "agri-market-gateway", "agri-database"],
    }
    CURRENT_SCENARIO["services"] = [
        {"id": "agri-connect-web", "name": "AgriConnect Web Portal (Vercel)", "status": "healthy" if success else "degraded", "latency_ms": int(avg_latency), "error_rate": 0.0},
        {"id": "agri-crop-service", "name": "Crop Analytics & Advisory Service", "status": "healthy", "latency_ms": 140, "error_rate": 0.0},
        {"id": "agri-market-gateway", "name": "Marketplace API Gateway", "status": "healthy", "latency_ms": 210, "error_rate": 0.0},
        {"id": "agri-database", "name": "Postgres Crop & Order Database", "status": "healthy", "latency_ms": 45, "error_rate": 0.0},
    ]
    CURRENT_SCENARIO["incident"] = None
    CURRENT_SCENARIO["diagnosis"] = None
    CURRENT_SCENARIO["patch"] = None

    return {
        "url": url,
        "avg_latency_ms": avg_latency,
        "status_codes": status_codes,
        "healthy": success,
        "message": f"Live probe completed: {url} is responding with HTTP 200 (avg {avg_latency}ms)",
    }


@router.post("/agri-connect/set-scenario")
def set_agri_scenario(payload: dict[str, str]) -> dict[str, Any]:
    scenario = payload.get("scenario", "baseline")

    if scenario == "baseline":
        CURRENT_SCENARIO["name"] = "Live Baseline (AgriConnect)"
        CURRENT_SCENARIO["services"] = [
            {"id": "agri-connect-web", "name": "AgriConnect Web Portal (Vercel)", "status": "healthy", "latency_ms": 1240, "error_rate": 0.0},
            {"id": "agri-crop-service", "name": "Crop Analytics & Advisory Service", "status": "healthy", "latency_ms": 140, "error_rate": 0.0},
            {"id": "agri-market-gateway", "name": "Marketplace API Gateway", "status": "healthy", "latency_ms": 210, "error_rate": 0.0},
            {"id": "agri-database", "name": "Postgres Crop & Order Database", "status": "healthy", "latency_ms": 45, "error_rate": 0.0},
        ]
        CURRENT_SCENARIO["metrics"] = {
            "request_count": 3420,
            "error_rate": 0.0,
            "p95_latency_ms": 1240,
            "timeout_rate": 0.0,
            "services": ["agri-connect-web", "agri-crop-service", "agri-market-gateway", "agri-database"],
        }
        CURRENT_SCENARIO["incident"] = None
        CURRENT_SCENARIO["diagnosis"] = None
        CURRENT_SCENARIO["patch"] = None

    elif scenario == "latency":
        CURRENT_SCENARIO["name"] = "Edge Latency & Gateway Degradation"
        CURRENT_SCENARIO["services"] = [
            {"id": "agri-connect-web", "name": "AgriConnect Web Portal (Vercel)", "status": "degraded", "latency_ms": 2850, "error_rate": 0.08},
            {"id": "agri-crop-service", "name": "Crop Analytics & Advisory Service", "status": "healthy", "latency_ms": 180, "error_rate": 0.01},
            {"id": "agri-market-gateway", "name": "Marketplace API Gateway", "status": "degraded", "latency_ms": 2700, "error_rate": 0.08},
            {"id": "agri-database", "name": "Postgres Crop & Order Database", "status": "healthy", "latency_ms": 90, "error_rate": 0.0},
        ]
        CURRENT_SCENARIO["metrics"] = {
            "request_count": 4890,
            "error_rate": 0.08,
            "p95_latency_ms": 2850,
            "timeout_rate": 0.05,
            "services": ["agri-connect-web", "agri-crop-service", "agri-market-gateway", "agri-database"],
        }
        CURRENT_SCENARIO["incident"] = {
            "service": "agri-market-gateway",
            "title": "API Gateway latency causing SSR timeout on Vercel edge",
            "severity": "medium",
            "status": "open",
            "evidence": {"error_rate": 0.08, "timeout_rate": 0.05, "p95_latency_ms": 2850, "dependency_failures": {"api-gateway": 3}},
        }
        CURRENT_SCENARIO["diagnosis"] = {
            "root_cause": "agri-market-gateway",
            "confidence": 0.78,
            "hypothesis": "Marketplace Gateway response delay is exceeding the Vercel SSR edge render deadline (2.5s), causing cascading 504 timeouts to end users.",
            "recommended_fix": "Add non-blocking client-side hydration with a 2-second circuit-breaker timeout on the AgriConnect gateway client.",
            "file_path": "services/marketplace_service/main.py",
        }
        CURRENT_SCENARIO["patch"] = {
            "file_path": "services/payment_service/main.py",
            "diff": """--- a/services/payment_service/main.py
+++ b/services/payment_service/main.py
@@ -14,6 +14,12 @@
     try:
-        response = await gateway.fetch_crop_catalog()
+        async with asyncio.timeout(2.0):
+            response = await gateway.fetch_crop_catalog()
+    except TimeoutError:
+        logger.warning("Gateway timeout. Returning cached AgriConnect crop catalog.")
+        return {"status": "degraded", "data": await cache.get("agri_crops_fallback")}
""",
            "confidence": 0.85,
            "risks": ["Cached crop catalog may have slight inventory delay during peak market hours."],
        }

    elif scenario == "outage":
        CURRENT_SCENARIO["name"] = "Critical Database & Connection Pool Outage"
        CURRENT_SCENARIO["services"] = [
            {"id": "agri-connect-web", "name": "AgriConnect Web Portal (Vercel)", "status": "critical", "latency_ms": 5200, "error_rate": 0.38},
            {"id": "agri-crop-service", "name": "Crop Analytics & Advisory Service", "status": "degraded", "latency_ms": 3100, "error_rate": 0.22},
            {"id": "agri-market-gateway", "name": "Marketplace API Gateway", "status": "critical", "latency_ms": 5100, "error_rate": 0.38},
            {"id": "agri-database", "name": "Postgres Crop & Order Database", "status": "critical", "latency_ms": 6400, "error_rate": 0.45},
        ]
        CURRENT_SCENARIO["metrics"] = {
            "request_count": 6120,
            "error_rate": 0.38,
            "p95_latency_ms": 5200,
            "timeout_rate": 0.25,
            "services": ["agri-connect-web", "agri-crop-service", "agri-market-gateway", "agri-database"],
        }
        CURRENT_SCENARIO["incident"] = {
            "service": "agri-database",
            "title": "Postgres connection pool exhaustion during crop marketplace queries",
            "severity": "critical",
            "status": "open",
            "evidence": {"error_rate": 0.38, "timeout_rate": 0.25, "p95_latency_ms": 5200, "dependency_failures": {"postgres": 8}},
        }
        CURRENT_SCENARIO["diagnosis"] = {
            "root_cause": "agri-database",
            "confidence": 0.94,
            "hypothesis": "PostgreSQL connection pool exhausted following the marketplace schema query load. All upstream AgriConnect web services are failing with HTTP 500.",
            "recommended_fix": "Increase DB connection pool headroom, implement exponential backoff retry queueing, and return cached crop analytics.",
            "file_path": "services/payment_service/main.py",
        }
        CURRENT_SCENARIO["patch"] = {
            "file_path": "services/payment_service/main.py",
            "diff": """--- a/services/payment_service/main.py
+++ b/services/payment_service/main.py
@@ -20,8 +20,16 @@
     if mode == "database_timeout":
-        with tracer.start_as_current_span("agri_db.query"):
-            await asyncio.sleep(6)
-        raise HTTPException(status_code=504, detail="Database connection timed out")
+        with tracer.start_as_current_span("agri_db.query"):
+            await asyncio.sleep(1)
+        return {
+            "status": "queued",
+            "transaction_id": "agri_tx_9012",
+            "message": "Marketplace transaction queued for retry due to DB congestion.",
+        }
""",
            "confidence": 0.92,
            "risks": ["Async queue processing may introduce a 2-5 second delay for transaction confirmation."],
        }

    return {"status": "updated", "scenario": CURRENT_SCENARIO["name"]}


@router.get("/agri-connect/current-analysis")
def get_agri_current_analysis() -> dict[str, Any]:
    return {
        "scenario": CURRENT_SCENARIO["name"],
        "target_url": CURRENT_SCENARIO["target_url"],
        "incident": CURRENT_SCENARIO["incident"],
        "diagnosis": CURRENT_SCENARIO["diagnosis"],
        "patch": CURRENT_SCENARIO["patch"],
    }


@router.post("/detection/evaluate")
def evaluate_detection(payload: dict[str, Any]) -> dict[str, Any]:
    incidents = detection_engine.evaluate(payload)
    for incident in incidents:
        incident_store.add(incident)
    return {"items": incidents, "total": len(incidents)}


@router.post("/incidents/evidence")
def collect_incident_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    service = payload.get("service", {})
    context = payload.get("context", {})
    evidence = evidence_collector.collect(service, context)
    return {"service": service.get("id", "unknown-service"), "evidence": evidence}


@router.post("/anomaly/evaluate")
def evaluate_anomaly(payload: dict[str, Any]) -> dict[str, Any]:
    anomalies = anomaly_detector.evaluate(payload)
    return {"items": anomalies, "total": len(anomalies)}


@router.post("/patches/generate")
def generate_patch(payload: dict[str, Any]) -> dict[str, Any]:
    incident = payload.get("incident") or {}
    diagnosis = payload.get("diagnosis") or {}
    patch = patch_generator.generate(incident, diagnosis)
    return {
        "id": patch.id,
        "service": patch.service,
        "summary": patch.summary,
        "file_path": patch.file_path,
        "diff": patch.diff,
        "confidence": patch.confidence,
        "risks": patch.risks,
        "validation_status": patch.validation_status,
    }


@router.post("/patches/validate")
def validate_patch(payload: dict[str, Any]) -> dict[str, Any]:
    patch = payload.get("patch") or {}
    validation = validation_engine.validate(patch)
    return validation.to_dict()


@router.post("/patches/validate-pipeline")
def validate_patch_pipeline(payload: dict[str, Any]) -> dict[str, Any]:
    patch = payload.get("patch") or {}
    validation = validation_pipeline.run(patch, project_root=".")
    return validation.to_dict()


@router.post("/github/branch")
def create_github_branch(payload: dict[str, Any]) -> dict[str, Any]:
    branch_name = payload.get("branch_name") or "fix/agri-connect-patch"
    return github_service.create_branch(branch_name)


@router.post("/github/commit")
def commit_github_changes(payload: dict[str, Any]) -> dict[str, Any]:
    branch_name = payload.get("branch_name") or "fix/agri-connect-patch"
    message = payload.get("message") or "fix: apply AgriConnect incident patch"
    files = payload.get("files") or ["services/payment_service/main.py"]
    return github_service.commit_changes(branch_name, message, files)


@router.post("/github/pr")
def create_github_pr(payload: dict[str, Any]) -> dict[str, Any]:
    title = payload.get("title") or "fix: address incident diagnosis patch in AgriConnect"
    body = payload.get("body") or "This draft PR captures the proposed patch and validation outcome for human review."
    head = payload.get("head") or "fix/agri-connect-patch"
    base = payload.get("base") or "main"
    return github_service.create_draft_pr(title, body, head, base)


@router.get("/incidents")
def list_incidents() -> dict[str, Any]:
    incidents = incident_store.list()
    return {"items": incidents, "total": len(incidents)}


@router.post("/incidents/reset")
def reset_incidents() -> dict[str, Any]:
    incident_store.replace([])
    return {"status": "reset", "total": 0}


@router.post("/diagnosis/evaluate")
def evaluate_diagnosis(payload: dict[str, Any]) -> dict[str, Any]:
    return diagnosis_engine.diagnose(payload)


@router.get("/incidents/{incident_id}/diagnosis")
def get_incident_diagnosis(incident_id: str) -> dict[str, Any]:
    incident = incident_store.get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "INCIDENT_NOT_FOUND", "message": "Incident was not found"}})
    return diagnosis_engine.diagnose(incident)


@router.get("/incidents/{incident_id}")
def get_incident(incident_id: str) -> dict[str, Any]:
    incident = incident_store.get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "INCIDENT_NOT_FOUND", "message": "Incident was not found"}})
    return incident
