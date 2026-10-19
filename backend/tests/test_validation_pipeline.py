from app.validation.engine import ValidationEngine
from app.validation.pipeline import ValidationPipeline
from app.patching.engine import PatchGenerator


def test_validation_engine_accepts_valid_patch() -> None:
    validation = ValidationEngine()
    patch = {
        "diff": "--- a/services/payment_service/main.py\n+++ b/services/payment_service/main.py\n@@ -1 +1 @@\n-old\n+new\n",
    }

    result = validation.validate(patch)

    assert result.passed is True
    assert "unit_test_run" not in result.checks
    assert "have not run" in result.summary


def test_validation_pipeline_runs_against_project_tests() -> None:
    validation = ValidationPipeline()
    patch = {
        "diff": PatchGenerator().generate(
            {"service": "payment-service", "evidence": {}},
            {"root_cause": "database timeout"},
        ).diff,
    }

    result = validation.run(patch, project_root="..")

    assert result.passed is True
    assert result.details["patch_apply"] == "passed"
    assert result.details["behavior_check"] == "passed"
    assert result.details["unit_test_run"] == "passed"


def test_validation_pipeline_rejects_path_traversal() -> None:
    validation = ValidationPipeline()
    patch = {
        "diff": "--- a/services/payment_service/../../backend/app/main.py\n"
        "+++ b/services/payment_service/../../backend/app/main.py\n"
        "@@ -1 +1 @@\n-old\n+new\n",
    }

    result = validation.run(patch, project_root="..")

    assert result.passed is False
    assert result.details["format_check"] == "failed"
