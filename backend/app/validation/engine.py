from __future__ import annotations

from typing import Any

from app.validation.patch_safety import validate_patch_diff


class ValidationResult:
    def __init__(
        self,
        passed: bool,
        checks: list[str],
        summary: str,
        details: dict[str, str] | None = None,
    ) -> None:
        self.passed = passed
        self.checks = checks
        self.summary = summary
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": self.checks,
            "summary": self.summary,
            "details": self.details,
        }


class ValidationEngine:
    """Run a minimal validation pipeline for generated patch proposals."""

    def validate(self, patch: Any) -> ValidationResult:
        if isinstance(patch, dict):
            diff = patch.get("diff", "")
        else:
            diff = getattr(patch, "diff", "")
        checks = ["format_check", "target_check"]
        try:
            validate_patch_diff(diff)
        except (TypeError, ValueError) as exc:
            return ValidationResult(False, checks, str(exc), {"format_check": "failed"})
        return ValidationResult(
            True,
            checks,
            "Patch is a single-file diff for an approved demo service; application and tests have not run.",
            {"format_check": "passed", "target_check": "passed"},
        )
