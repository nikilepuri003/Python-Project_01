from app.detection.engine import DetectionEngine


def test_healthy_snapshot_does_not_create_incident() -> None:
    engine = DetectionEngine()

    snapshot = {
        "services": [
            {
                "id": "user-service",
                "status": "healthy",
                "error_rate": 0.01,
                "timeout_rate": 0.0,
                "p95_latency_ms": 120,
            },
            {
                "id": "order-service",
                "status": "healthy",
                "error_rate": 0.02,
                "timeout_rate": 0.0,
                "p95_latency_ms": 180,
            },
            {
                "id": "payment-service",
                "status": "healthy",
                "error_rate": 0.01,
                "timeout_rate": 0.0,
                "p95_latency_ms": 110,
            },
        ]
    }

    incidents = engine.evaluate(snapshot)

    assert incidents == []


def test_payment_dependency_failure_creates_incident() -> None:
    engine = DetectionEngine()

    snapshot = {
        "services": [
            {
                "id": "user-service",
                "status": "healthy",
                "error_rate": 0.01,
                "timeout_rate": 0.0,
                "p95_latency_ms": 120,
            },
            {
                "id": "order-service",
                "status": "degraded",
                "error_rate": 0.31,
                "timeout_rate": 0.22,
                "p95_latency_ms": 3100,
                "dependency_failures": {"payment-service": 5},
            },
            {
                "id": "payment-service",
                "status": "degraded",
                "error_rate": 0.42,
                "timeout_rate": 0.33,
                "p95_latency_ms": 4700,
                "dependency_failures": {"database": 2},
            },
        ]
    }

    incidents = engine.evaluate(snapshot)

    assert len(incidents) == 1
    assert incidents[0]["service"] == "payment-service"
    assert incidents[0]["status"] == "open"
    assert incidents[0]["severity"] == "high"
    assert incidents[0]["title"] == "Payment service degraded"
