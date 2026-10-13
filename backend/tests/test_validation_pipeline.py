from app.validation.engine import ValidationEngine
from app.validation.pipeline import ValidationPipeline


def test_validation_engine_accepts_valid_patch() -> None:
    validation = ValidationEngine()
    patch = {
        "diff": "--- a/services/payment_service/main.py\n+++ b/services/payment_service/main.py\n@@\n-old\n+new\n",
    }

    result = validation.validate(patch)

    assert result.passed is True
    assert "unit_test_run" in result.checks


def test_validation_pipeline_runs_against_project_tests() -> None:
    validation = ValidationPipeline()
    patch = {
        "diff": "--- a/services/payment_service/main.py\n+++ b/services/payment_service/main.py\n@@\n-old\n+new\n",
    }

    result = validation.run(patch, project_root=".")

    assert result.passed is True
    assert result.summary.startswith("Patch proposal passed")
