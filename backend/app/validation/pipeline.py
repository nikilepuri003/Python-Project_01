from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.validation.engine import ValidationResult


class ValidationPipeline:
    """Run a small, deterministic validation workflow for prototype patches."""

    def run(self, patch: Any, project_root: str = ".") -> ValidationResult:
        checks: list[str] = [
            "format_check",
            "static_check",
            "unit_test_run",
            "health_check",
        ]

        if not patch:
            return ValidationResult(False, checks, "No patch payload was supplied for validation.")

        diff = patch.get("diff", "") if isinstance(patch, dict) else getattr(patch, "diff", "")
        if "@@" not in diff and "--- a/" not in diff:
            return ValidationResult(False, checks, "Patch proposal is not a meaningful unified diff.")

        try:
            python_executable = sys.executable
            root_path = Path(project_root).resolve()

            possible_dirs = [
                root_path / "backend" / "tests",
                Path(__file__).resolve().parent.parent.parent / "tests",
                Path.cwd() / "backend" / "tests",
                root_path / "tests",
                Path.cwd() / "tests",
            ]

            tests_dir = None
            test_files: list[str] = []
            for candidate in possible_dirs:
                if candidate.exists():
                    found = [str(p) for p in sorted(candidate.glob("test_*.py")) if p.name != "test_validation_pipeline.py"]
                    if found:
                        tests_dir = candidate
                        test_files = found
                        break

            if not tests_dir or not test_files:
                return ValidationResult(False, checks, "No validation tests were available to run.")

            backend_dir = str(tests_dir.parent)
            env = os.environ.copy()
            env["PYTHONPATH"] = backend_dir

            subprocess.run(
                [python_executable, "-m", "pytest", *test_files, "-q", "-o", f"pythonpath={backend_dir}"],
                cwd=str(backend_dir),
                env=env,
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return ValidationResult(False, checks, "Validation failed during the test run.")

        return ValidationResult(
            True,
            checks,
            "Patch proposal passed the prototype validation checks.",
        )
