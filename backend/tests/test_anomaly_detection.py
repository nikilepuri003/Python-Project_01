from app.anomaly.engine import AnomalyDetector


def test_anomaly_detector_flags_unusual_service_behavior() -> None:
    detector = AnomalyDetector()
    snapshot = {
        "services": [
            {
                "id": "user-service",
                "request_count": 100,
                "error_rate": 0.01,
                "mean_latency_ms": 90,
                "p95_latency_ms": 160,
                "timeout_rate": 0.01,
            },
            {
                "id": "order-service",
                "request_count": 120,
                "error_rate": 0.02,
                "mean_latency_ms": 140,
                "p95_latency_ms": 220,
                "timeout_rate": 0.02,
            },
            {
                "id": "payment-service",
                "request_count": 500,
                "error_rate": 0.8,
                "mean_latency_ms": 8200,
                "p95_latency_ms": 9900,
                "timeout_rate": 0.7,
            },
        ]
    }

    anomalies = detector.evaluate(snapshot)

    assert len(anomalies) >= 1
    assert anomalies[0]["service"] == "payment-service"
    assert anomalies[0]["is_anomaly"] is True
