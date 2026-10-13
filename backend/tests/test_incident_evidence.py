from app.incidents.evidence import IncidentEvidenceCollector, IncidentNormalizer


def test_incident_evidence_collector_builds_score() -> None:
    collector = IncidentEvidenceCollector()
    evidence = collector.collect(
        {
            "id": "payment-service",
            "error_rate": 0.4,
            "timeout_rate": 0.25,
            "p95_latency_ms": 5200,
            "dependency_failures": {"database": 3},
            "logs": ["error: payment database exception", "retrying query"],
            "trace_ids": ["trace-1"],
            "dependencies": ["database"],
            "recent_changes": ["db timeout setting changed"],
        }
    )

    assert evidence["score"] > 0.5
    assert evidence["dependency_failures"]["database"] == 3
    assert evidence["trace_dependency_match"] == 1.0


def test_incident_normalizer_keeps_status_and_summary_consistent() -> None:
    normalizer = IncidentNormalizer()
    incident = normalizer.normalize(
        {
            "service": "payment-service",
            "title": "Payment service degraded",
            "severity": "high",
            "status": "DETECTED",
            "evidence": {
                "error_rate": 0.42,
                "timeout_rate": 0.33,
                "p95_latency_ms": 4700,
                "dependency_failures": {"database": 2},
                "logs": ["database timeout exception"],
                "trace_ids": ["trace-42"],
                "recent_changes": ["DB config update"],
            },
        }
    )

    assert incident["service"] == "payment-service"
    assert incident["severity"] == "high"
    assert incident["status"] == "open"
    assert "error_rate=0.42" in incident["summary"]
    assert incident["evidence"]["score"] > 0.0
