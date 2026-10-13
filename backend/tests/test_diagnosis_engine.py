from app.diagnosis.engine import DiagnosisEngine


def test_payment_incident_recommends_payment_root_cause() -> None:
    engine = DiagnosisEngine()
    incident = {
        "service": "payment-service",
        "title": "Payment service degraded",
        "severity": "high",
        "status": "open",
        "evidence": {
            "error_rate": 0.42,
            "timeout_rate": 0.33,
            "p95_latency_ms": 4700,
            "dependency_failures": {"database": 2},
        },
    }

    diagnosis = engine.diagnose(incident)

    assert diagnosis["root_cause"] == "payment-service"
    assert diagnosis["confidence"] >= 0.8
    assert "database" in diagnosis["evidence_summary"].lower()
    assert "payment-service" in diagnosis["recommended_action"].lower()


def test_healthy_incident_has_low_confidence() -> None:
    engine = DiagnosisEngine()
    incident = {
        "service": "user-service",
        "title": "User service degraded",
        "severity": "medium",
        "status": "open",
        "evidence": {
            "error_rate": 0.1,
            "timeout_rate": 0.05,
            "p95_latency_ms": 900,
            "dependency_failures": {},
        },
    }

    diagnosis = engine.diagnose(incident)

    assert diagnosis["root_cause"] == "user-service"
    assert diagnosis["confidence"] < 0.7
