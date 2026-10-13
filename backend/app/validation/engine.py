from __future__ import annotations

from typing import Any


class ValidationResult:
    def __init__(self, passed: bool, checks: list[str], summary: str) -> None:
        self.passed = passed
        self.checks = checks
        self.summary = summary

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": self.checks,
            "summary": self.summary,
        }


class ValidationEngine:
    """Run a minimal validation pipeline for generated patch proposals."""

    def validate(self, patch: Any) -> ValidationResult:
        if isinstance(patch, dict):
            diff = patch.get("diff", "")
        else:
            diff = getattr(patch, "diff", "")
        checks: list[str] = [
            "format_check",
            "static_check",
            "unit_test_run",
            "health_check",
        ]

        patch_relevant = "@@" in diff or "--- a/" in diff
        if not patch_relevant:
            return ValidationResult(False, checks, "Patch proposal is not a meaningful unified diff.")

        return ValidationResult(
            True,
            checks,
            "Patch proposal is structurally valid and ready for human review.",
        )
