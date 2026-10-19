from app.patching.engine import PatchGenerator
from app.validation.engine import ValidationEngine
from app.validation.pipeline import ValidationPipeline


def test_patch_generator_creates_minimal_diff_for_payment_service() -> None:
    engine = PatchGenerator()
    incident = {
        "service": "payment-service",
        "evidence": {
            "error_rate": 0.42,
            "timeout_rate": 0.33,
            "p95_latency_ms": 4700,
            "dependency_failures": {"database": 2},
        },
    }
    diagnosis = {
        "root_cause": "payment-service",
        "confidence": 0.92,
        "recommended_fix": "Validate the dependency timeout and queue the payment before retrying.",
    }

    patch = engine.generate(incident, diagnosis)

    assert patch.service == "payment-service"
    assert patch.file_path == "services/payment_service/main.py"
    assert "--- a/services/payment_service/main.py" in patch.diff
    assert patch.confidence >= 0.7
    assert len(patch.risks) >= 1
    assert "status" in patch.diff and "queued" in patch.diff


def test_validation_engine_accepts_patch_with_unified_diff() -> None:
    validation = ValidationEngine()
    patch = {
        "diff": "--- a/services/payment_service/main.py\n+++ b/services/payment_service/main.py\n@@ -1 +1 @@\n-old\n+new\n",
    }

    result = validation.validate(patch)

    assert result.passed is True
    assert result.details["target_check"] == "passed"
