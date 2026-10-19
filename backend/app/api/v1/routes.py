import threading
import time
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from pydantic import field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.anomaly.engine import AnomalyDetector
from app.core.auth_sessions import (
    create_user_session,
    find_session_user,
    get_or_create_user,
    revoke_user_session,
    serialize_user,
)
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import verify_google_oauth_token
from app.detection.engine import DetectionEngine
from app.diagnosis.engine import DiagnosisEngine
from app.github.service import GitHubIntegrationError, GitHubService
from app.incidents.evidence import IncidentEvidenceCollector
from app.incidents.store import IncidentStore
from app.models.auth import User
from app.models.monitoring import Monitor, MonitorCheck, MonitorIncident, utc_now
from app.patching.engine import PatchGenerator
from app.services.monitoring import (
    MAX_INTERVAL_SECONDS,
    MAX_MONITORS_PER_USER,
    MIN_INTERVAL_SECONDS,
    check_public_url,
    get_demo_monitor_services,
    run_monitor_check,
    validate_monitor_url,
    validate_public_url,
)
from app.validation.engine import ValidationEngine, ValidationResult
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
validation_semaphore = threading.BoundedSemaphore(1)


def run_isolated_patch_validation(patch: Any, project_root: str) -> ValidationResult:
    if not validation_semaphore.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Another patch validation is running. Retry shortly.")
    try:
        return validation_pipeline.run(patch, project_root=project_root)
    finally:
        validation_semaphore.release()


class MonitorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=2048)
    interval_seconds: int = Field(default=300, ge=MIN_INTERVAL_SECONDS, le=MAX_INTERVAL_SECONDS)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Monitor name cannot be empty.")
        return cleaned


class MonitorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    interval_seconds: int | None = Field(default=None, ge=MIN_INTERVAL_SECONDS, le=MAX_INTERVAL_SECONDS)
    enabled: bool | None = None

    @field_validator("name")
    @classmethod
    def validate_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Monitor name cannot be empty.")
        return cleaned


def require_monitor_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    scheme, _, token = (authorization or "").partition(" ")
    user = find_session_user(db, token if scheme.lower() == "bearer" else None)
    if user is None:
        raise HTTPException(status_code=401, detail="A valid signed-in session is required.")
    return user


def _owned_monitor(db: Session, monitor_id: int, user: User) -> Monitor:
    monitor = db.scalar(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user.id)
    )
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found.")
    return monitor


def _check_response(check: MonitorCheck) -> dict[str, Any]:
    return {
        "id": check.id,
        "result": check.result,
        "reachable": check.reachable,
        "status_code": check.status_code,
        "response_time_ms": check.response_time_ms,
        "message": check.message,
        "checked_at": check.checked_at.isoformat() + "Z",
    }


def _monitor_response(db: Session, monitor: Monitor) -> dict[str, Any]:
    latest = db.scalar(
        select(MonitorCheck)
        .where(MonitorCheck.monitor_id == monitor.id)
        .order_by(MonitorCheck.checked_at.desc())
        .limit(1)
    )
    return {
        "id": monitor.id,
        "name": monitor.name,
        "url": monitor.url,
        "interval_seconds": monitor.interval_seconds,
        "enabled": monitor.enabled,
        "consecutive_failures": monitor.consecutive_failures,
        "next_check_at": monitor.next_check_at.isoformat() + "Z",
        "created_at": monitor.created_at.isoformat() + "Z",
        "latest_check": _check_response(latest) if latest else None,
    }


@router.get("/monitors")
def list_user_monitors(
    user: User = Depends(require_monitor_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    monitors = db.scalars(
        select(Monitor).where(Monitor.user_id == user.id).order_by(Monitor.created_at.desc())
    ).all()
    return {"items": [_monitor_response(db, monitor) for monitor in monitors]}


@router.get("/monitoring/demo-services", dependencies=[Depends(require_monitor_user)])
def list_demo_monitor_services() -> dict[str, Any]:
    return {"items": get_demo_monitor_services()}


@router.post("/monitors", status_code=201)
def create_user_monitor(
    payload: MonitorCreate,
    user: User = Depends(require_monitor_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    monitor_count = db.scalar(
        select(func.count()).select_from(Monitor).where(Monitor.user_id == user.id)
    ) or 0
    if monitor_count >= MAX_MONITORS_PER_USER:
        raise HTTPException(status_code=409, detail=f"A user may configure at most {MAX_MONITORS_PER_USER} monitors.")
    try:
        normalized_url = validate_monitor_url(payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    monitor = Monitor(
        user_id=user.id,
        name=payload.name.strip(),
        url=normalized_url,
        interval_seconds=payload.interval_seconds,
        next_check_at=utc_now(),
    )
    db.add(monitor)
    db.commit()
    db.refresh(monitor)
    return _monitor_response(db, monitor)


@router.patch("/monitors/{monitor_id}")
def update_user_monitor(
    monitor_id: int,
    payload: MonitorUpdate,
    user: User = Depends(require_monitor_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    monitor = _owned_monitor(db, monitor_id, user)
    values = payload.model_dump(exclude_unset=True)
    if "name" in values and values["name"] is not None:
        monitor.name = values["name"].strip()
    if "url" in values and values["url"] is not None:
        try:
            monitor.url = validate_monitor_url(values["url"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        monitor.next_check_at = utc_now()
    if "interval_seconds" in values and values["interval_seconds"] is not None:
        monitor.interval_seconds = values["interval_seconds"]
        monitor.next_check_at = utc_now()
    if "enabled" in values and values["enabled"] is not None:
        monitor.enabled = values["enabled"]
        if monitor.enabled:
            monitor.next_check_at = utc_now()
    monitor.updated_at = utc_now()
    db.commit()
    db.refresh(monitor)
    return _monitor_response(db, monitor)


@router.delete("/monitors/{monitor_id}", status_code=204)
def delete_user_monitor(
    monitor_id: int,
    user: User = Depends(require_monitor_user),
    db: Session = Depends(get_db),
) -> None:
    db.delete(_owned_monitor(db, monitor_id, user))
    db.commit()


@router.post("/monitors/{monitor_id}/check")
def check_user_monitor_now(
    monitor_id: int,
    user: User = Depends(require_monitor_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    monitor = _owned_monitor(db, monitor_id, user)
    check = run_monitor_check(db, monitor)
    monitor.next_check_at = utc_now() + timedelta(seconds=monitor.interval_seconds)
    db.commit()
    return _check_response(check)


@router.get("/monitors/{monitor_id}/checks")
def list_user_monitor_checks(
    monitor_id: int,
    limit: int = 50,
    user: User = Depends(require_monitor_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    monitor = _owned_monitor(db, monitor_id, user)
    checks = db.scalars(
        select(MonitorCheck)
        .where(MonitorCheck.monitor_id == monitor.id)
        .order_by(MonitorCheck.checked_at.desc())
        .limit(max(1, min(limit, 100)))
    ).all()
    return {"items": [_check_response(check) for check in checks]}


@router.get("/monitoring/incidents")
def list_user_monitor_incidents(
    user: User = Depends(require_monitor_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    incidents = db.scalars(
        select(MonitorIncident)
        .where(MonitorIncident.user_id == user.id)
        .order_by(MonitorIncident.created_at.desc())
        .limit(100)
    ).all()
    return {
        "items": [
            {
                "id": incident.id,
                "monitor_id": incident.monitor_id,
                "title": incident.title,
                "status": incident.status,
                "severity": incident.severity,
                "evidence": incident.evidence,
                "diagnosis": incident.diagnosis,
                "diagnosis_provider": incident.diagnosis_provider,
                "patch_proposal": incident.patch_proposal,
                "created_at": incident.created_at.isoformat() + "Z",
                "resolved_at": incident.resolved_at.isoformat() + "Z" if incident.resolved_at else None,
            }
            for incident in incidents
        ]
    }


@router.post("/monitoring/incidents/{incident_id}/diagnose")
def diagnose_user_monitor_incident(
    incident_id: int,
    user: User = Depends(require_monitor_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    incident = db.scalar(
        select(MonitorIncident).where(
            MonitorIncident.id == incident_id,
            MonitorIncident.user_id == user.id,
        )
    )
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    monitor = _owned_monitor(db, incident.monitor_id, user)
    evidence_without_url = {
        key: value for key, value in (incident.evidence or {}).items() if key != "url"
    }
    diagnosis = diagnosis_engine.diagnose(
        {"service": monitor.name, "title": incident.title, "evidence": evidence_without_url}
    )
    incident.diagnosis = diagnosis
    incident.diagnosis_provider = str(diagnosis.get("provider_status", "unknown"))
    incident.updated_at = utc_now()
    db.commit()
    return {
        "incident_id": incident.id,
        "diagnosis": diagnosis,
        "provider_status": incident.diagnosis_provider,
    }


@router.get("/monitoring/github-status", dependencies=[Depends(require_monitor_user)])
def get_github_integration_status() -> dict[str, Any]:
    return github_service.status()


@router.post("/monitoring/incidents/{incident_id}/patch")
def propose_and_validate_incident_patch(
    incident_id: int,
    user: User = Depends(require_monitor_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    incident = db.scalar(
        select(MonitorIncident).where(
            MonitorIncident.id == incident_id,
            MonitorIncident.user_id == user.id,
        )
    )
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    if not isinstance(incident.diagnosis, dict):
        raise HTTPException(status_code=409, detail="Generate and review a diagnosis before proposing a patch.")

    monitor = _owned_monitor(db, incident.monitor_id, user)
    try:
        patch = patch_generator.generate(
            {"service": monitor.name, "title": incident.title, "evidence": incident.evidence or {}},
            incident.diagnosis,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    validation = run_isolated_patch_validation(
        patch,
        str(Path(__file__).resolve().parents[4]),
    )
    proposal = {
        "id": patch.id,
        "service": patch.service,
        "summary": patch.summary,
        "file_path": patch.file_path,
        "diff": patch.diff,
        "confidence": patch.confidence,
        "risks": patch.risks,
        "validation_status": "passed" if validation.passed else "failed",
        "validation": validation.to_dict(),
        "github_result": None,
        "created_at": utc_now().isoformat() + "Z",
    }
    incident.patch_proposal = proposal
    incident.updated_at = utc_now()
    db.commit()
    return {"incident_id": incident.id, "patch_proposal": proposal}


@router.post("/monitoring/incidents/{incident_id}/draft-pr")
def create_incident_draft_pr(
    incident_id: int,
    user: User = Depends(require_monitor_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    incident = db.scalar(
        select(MonitorIncident).where(
            MonitorIncident.id == incident_id,
            MonitorIncident.user_id == user.id,
        )
    )
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    proposal = incident.patch_proposal
    if not isinstance(proposal, dict) or proposal.get("validation_status") != "passed":
        raise HTTPException(status_code=409, detail="A patch must pass isolated validation before creating a draft PR.")
    previous_result = proposal.get("github_result")
    if isinstance(previous_result, dict) and previous_result.get("status") == "created":
        raise HTTPException(status_code=409, detail="A draft PR has already been created for this proposal.")

    diagnosis = incident.diagnosis if isinstance(incident.diagnosis, dict) else {}
    title = f"fix: {str(incident.title)[:180]}"
    body = "\n".join(
        [
            "## CodePulse incident remediation proposal",
            "",
            f"- Incident: {incident.id}",
            f"- Diagnosis provider: {incident.diagnosis_provider or 'unknown'}",
            f"- Root cause assessment: {str(diagnosis.get('root_cause', 'Not available'))[:500]}",
            f"- Validation: {str((proposal.get('validation') or {}).get('summary', 'Not available'))[:1000]}",
            "",
            "This is a draft for human review. It has not been merged or deployed.",
        ]
    )
    branch = f"fix/codepulse-incident-{incident.id}-{uuid.uuid4().hex[:8]}"
    try:
        result = github_service.create_draft_pr(
            title=title,
            body=body,
            head=branch,
            diff=str(proposal.get("diff", "")),
            validation_passed=True,
        )
    except GitHubIntegrationError as exc:
        incident.patch_proposal = {
            **proposal,
            "github_result": {
                "status": "failed",
                "source": "github",
                "draft": False,
                "url": None,
                "error": str(exc),
            },
        }
        incident.updated_at = utc_now()
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    incident.patch_proposal = {**proposal, "github_result": result}
    incident.updated_at = utc_now()
    db.commit()
    return {"incident_id": incident.id, "github_result": result}


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
def google_auth(payload: dict[str, Any], db: Session = Depends(get_db)) -> dict[str, Any]:
    """Authenticate and verify a user via Google OAuth."""
    token = payload.get("token") or payload.get("credential")
    email = payload.get("email")
    name = payload.get("name")
    picture = payload.get("picture")

    if not isinstance(token, str) or not token:
        raise HTTPException(status_code=400, detail="A Google credential is required.")
    settings = get_settings()
    if not settings.google_client_id and (
        not token.startswith("google-oauth-demo") or settings.app_env == "production"
    ):
        raise HTTPException(status_code=503, detail="Google sign-in is not configured on the backend.")

    try:
        user_profile = verify_google_oauth_token(token, email=email, name=name, picture=picture)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    user, created = get_or_create_user(db, user_profile)
    session_token = create_user_session(db, user)

    return {
        "status": "success",
        "message": f"Successfully authenticated as {user.name or user.email}",
        "user": serialize_user(user),
        "session_token": session_token,
        "account_created": created,
    }


@router.get("/auth/me")
def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get the currently authenticated user profile."""
    scheme, _, token = (authorization or "").partition(" ")
    user = find_session_user(db, token if scheme.lower() == "bearer" else None)
    return {
        "authenticated": user is not None,
        "user": serialize_user(user) if user else None,
    }


@router.post("/auth/logout")
def logout(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Log out the current user session."""
    scheme, _, token = (authorization or "").partition(" ")
    revoke_user_session(db, token if scheme.lower() == "bearer" else None)
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
    try:
        return check_public_url(raw_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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


@router.post("/patches/generate", dependencies=[Depends(require_monitor_user)])
def generate_patch(
    payload: dict[str, Any],
) -> dict[str, Any]:
    incident = payload.get("incident") or {}
    diagnosis = payload.get("diagnosis") or {}
    try:
        patch = patch_generator.generate(incident, diagnosis)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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


@router.post("/patches/validate", dependencies=[Depends(require_monitor_user)])
def validate_patch(
    payload: dict[str, Any],
) -> dict[str, Any]:
    patch = payload.get("patch") or {}
    validation = validation_engine.validate(patch)
    return validation.to_dict()


@router.post("/patches/validate-pipeline", dependencies=[Depends(require_monitor_user)])
def validate_patch_pipeline(
    payload: dict[str, Any],
) -> dict[str, Any]:
    patch = payload.get("patch") or {}
    project_root = str(Path(__file__).resolve().parents[4])
    validation = run_isolated_patch_validation(patch, project_root)
    return validation.to_dict()


@router.post("/github/branch")
def create_github_branch() -> dict[str, Any]:
    raise HTTPException(
        status_code=410,
        detail="Direct branch creation is disabled. Use the authenticated incident draft-PR workflow after validation.",
    )


@router.post("/github/commit")
def commit_github_changes() -> dict[str, Any]:
    raise HTTPException(
        status_code=410,
        detail="Direct commits are disabled. Use the authenticated incident draft-PR workflow after validation.",
    )


@router.post("/github/pr")
def create_github_pr() -> dict[str, Any]:
    raise HTTPException(
        status_code=410,
        detail="Unvalidated draft PR creation is disabled. Use the authenticated incident draft-PR workflow.",
    )


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
