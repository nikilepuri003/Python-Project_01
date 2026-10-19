from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import routes
from app.core.auth_sessions import create_user_session, get_or_create_user
from app.core.database import Base, get_db
from app.models.monitoring import Monitor, MonitorIncident
from app.validation.engine import ValidationResult


def test_authenticated_owner_can_validate_patch_and_get_truthful_mock_pr_state(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as db:
        owner, _ = get_or_create_user(
            db,
            {"sub": "remediation-owner", "email": "remediation@example.com", "name": "Owner"},
        )
        other, _ = get_or_create_user(
            db,
            {"sub": "remediation-other", "email": "other@example.com", "name": "Other"},
        )
        owner_token = create_user_session(db, owner)
        other_token = create_user_session(db, other)
        monitor = Monitor(
            user_id=owner.id,
            name="payment-service",
            url="https://payments.example",
            interval_seconds=300,
        )
        db.add(monitor)
        db.flush()
        incident = MonitorIncident(
            monitor_id=monitor.id,
            user_id=owner.id,
            status="open",
            severity="high",
            title="Payment database timeout",
            evidence={"result": "server_error", "status_code": 504},
            diagnosis={"root_cause": "Database timeout", "recommended_fix": "Queue the demo request."},
            diagnosis_provider="mock demo",
            created_at=datetime(2026, 1, 1),
        )
        db.add(incident)
        db.commit()
        incident_id = incident.id

    def override_db():
        with session_factory() as db:
            yield db

    class MockGitHub:
        def status(self):
            return {"mode": "mock", "configured": False, "repository": None, "base_branch": None}

        def create_draft_pr(self, **kwargs):
            assert kwargs["validation_passed"] is True
            return {
                "status": "not_configured",
                "source": "mock",
                "draft": False,
                "url": None,
                "note": "GitHub integration is not configured; no branch or pull request was created.",
            }

    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_db] = override_db
    validation_state = {"passed": False}
    monkeypatch.setattr(
        routes.validation_pipeline,
        "run",
        lambda patch, project_root: ValidationResult(
            validation_state["passed"],
            ["format_check", "patch_apply", "unit_test_run"],
            "Mock isolated validation passed." if validation_state["passed"] else "Mock validation failed.",
            {"format_check": "passed", "patch_apply": "passed", "unit_test_run": "passed" if validation_state["passed"] else "failed"},
        ),
    )
    monkeypatch.setattr(routes, "github_service", MockGitHub())
    try:
        with TestClient(app) as client:
            assert client.get("/api/v1/monitoring/github-status").status_code == 401
            assert client.get("/api/v1/monitoring/demo-services").status_code == 401
            demo_services = client.get(
                "/api/v1/monitoring/demo-services",
                headers={"Authorization": f"Bearer {owner_token}"},
            )
            assert {item["id"] for item in demo_services.json()["items"]} == {
                "payment-service",
                "order-service",
                "user-service",
            }
            assert client.post(
                f"/api/v1/monitoring/incidents/{incident_id}/patch",
                headers={"Authorization": f"Bearer {other_token}"},
            ).status_code == 404

            owner_headers = {"Authorization": f"Bearer {owner_token}"}
            assert client.post(
                f"/api/v1/monitoring/incidents/{incident_id}/draft-pr",
                headers=owner_headers,
            ).status_code == 409

            proposed = client.post(
                f"/api/v1/monitoring/incidents/{incident_id}/patch",
                headers=owner_headers,
            )
            assert proposed.status_code == 200
            proposal = proposed.json()["patch_proposal"]
            assert proposal["validation_status"] == "failed"
            assert client.post(
                f"/api/v1/monitoring/incidents/{incident_id}/draft-pr",
                headers=owner_headers,
            ).status_code == 409

            validation_state["passed"] = True
            proposed = client.post(
                f"/api/v1/monitoring/incidents/{incident_id}/patch",
                headers=owner_headers,
            )
            assert proposed.status_code == 200
            proposal = proposed.json()["patch_proposal"]
            assert proposal["validation_status"] == "passed"
            assert proposal["file_path"] == "services/payment_service/main.py"
            assert "database_timeout" in proposal["diff"]

            pr = client.post(
                f"/api/v1/monitoring/incidents/{incident_id}/draft-pr",
                headers=owner_headers,
            )
            assert pr.status_code == 200
            result = pr.json()["github_result"]
            assert result["source"] == "mock"
            assert result["status"] == "not_configured"
            assert result["url"] is None
            stored = client.get("/api/v1/monitoring/incidents", headers=owner_headers)
            assert stored.json()["items"][0]["patch_proposal"]["github_result"]["url"] is None
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
