from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from app.validation.engine import ValidationResult
from app.validation.patch_safety import validate_patch_diff

VALIDATION_TIMEOUT_SECONDS = 120


def _ignore_validation_files(_directory: str, names: list[str]) -> set[str]:
    del _directory
    ignored = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"}
    return {
        name
        for name in names
        if name in ignored or name.startswith(".env") or name.endswith((".db", ".sqlite"))
    }


class ValidationPipeline:
    """Apply a single approved demo patch in a disposable copy and run repository tests."""

    def run(self, patch: Any, project_root: str = ".") -> ValidationResult:
        checks = [
            "format_check",
            "target_check",
            "patch_apply",
            "syntax_check",
            "behavior_check",
            "unit_test_run",
        ]
        details: dict[str, str] = {name: "not_run" for name in checks}
        if not patch:
            return ValidationResult(False, checks, "No patch payload was supplied.", details)

        diff = patch.get("diff", "") if isinstance(patch, dict) else getattr(patch, "diff", "")
        try:
            file_path = validate_patch_diff(diff)
        except (TypeError, ValueError) as exc:
            details["format_check"] = "failed"
            return ValidationResult(False, checks, str(exc), details)
        details["format_check"] = "passed"

        source_root = Path(project_root).resolve()
        if not (source_root / "services").is_dir() and (source_root.parent / "services").is_dir():
            source_root = source_root.parent
        backend_source = source_root / "backend"
        service_source = source_root / PurePosixPath(file_path)
        if not backend_source.is_dir() or not (backend_source / "tests").is_dir():
            details["target_check"] = "failed"
            return ValidationResult(
                False,
                checks,
                "The configured workspace must contain backend/tests and the approved demo services.",
                details,
            )
        workspace_path = source_root
        has_symlink_component = False
        for path_part in PurePosixPath(file_path).parts:
            workspace_path = workspace_path / path_part
            has_symlink_component = has_symlink_component or workspace_path.is_symlink()
        if not service_source.is_file() or has_symlink_component:
            details["target_check"] = "failed"
            return ValidationResult(False, checks, "The patch target is missing or is not a regular file.", details)
        details["target_check"] = "passed"

        try:
            with tempfile.TemporaryDirectory(prefix="codepulse-patch-") as temporary_dir:
                workspace = Path(temporary_dir)
                backend_copy = workspace / "backend"
                shutil.copytree(backend_source, backend_copy, ignore=_ignore_validation_files)
                isolated_target = workspace / PurePosixPath(file_path)
                isolated_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(service_source, isolated_target)
                git_init = subprocess.run(
                    ["git", "init", "--quiet"],
                    cwd=workspace,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if git_init.returncode:
                    details["patch_apply"] = "failed"
                    return ValidationResult(False, checks, "Could not initialize the isolated patch workspace.", details)

                check_apply = subprocess.run(
                    ["git", "apply", "--check", "-"],
                    cwd=workspace,
                    input=diff,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if check_apply.returncode:
                    details["patch_apply"] = "failed"
                    return ValidationResult(False, checks, "Patch does not apply cleanly to its target file.", details)
                applied = subprocess.run(
                    ["git", "apply", "-"],
                    cwd=workspace,
                    input=diff,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if applied.returncode:
                    details["patch_apply"] = "failed"
                    return ValidationResult(False, checks, "Patch could not be applied in the isolated workspace.", details)
                details["patch_apply"] = "passed"

                patched_file = workspace / PurePosixPath(file_path)
                try:
                    module = ast.parse(patched_file.read_text(encoding="utf-8"), filename=file_path)
                except (OSError, SyntaxError, UnicodeError):
                    details["syntax_check"] = "failed"
                    return ValidationResult(False, checks, "Patched Python file failed syntax validation.", details)
                details["syntax_check"] = "passed"

                payment_handler = next(
                    (
                        node
                        for node in ast.walk(module)
                        if isinstance(node, ast.AsyncFunctionDef) and node.name == "process_payment"
                    ),
                    None,
                )
                database_timeout_branch = None
                if payment_handler is not None:
                    database_timeout_branch = next(
                        (
                            node
                            for node in ast.walk(payment_handler)
                            if isinstance(node, ast.If)
                            and isinstance(node.test, ast.Compare)
                            and isinstance(node.test.left, ast.Name)
                            and node.test.left.id == "mode"
                            and node.test.comparators
                            and isinstance(node.test.comparators[0], ast.Constant)
                            and node.test.comparators[0].value == "database_timeout"
                        ),
                        None,
                    )
                if database_timeout_branch is None:
                    details["behavior_check"] = "failed"
                    return ValidationResult(
                        False,
                        checks,
                        "The payment handler has no database-timeout branch.",
                        details,
                    )
                queued_return = next(
                    (
                        node
                        for node in ast.walk(database_timeout_branch)
                        if isinstance(node, ast.Return)
                        and isinstance(node.value, ast.Dict)
                        and any(
                            isinstance(key, ast.Constant)
                            and key.value == "status"
                            and isinstance(value, ast.Constant)
                            and value.value == "queued"
                            for key, value in zip(node.value.keys, node.value.values)
                        )
                    ),
                    None,
                )
                if queued_return is None or any(
                    isinstance(node, ast.Raise) for node in ast.walk(database_timeout_branch)
                ):
                    details["behavior_check"] = "failed"
                    return ValidationResult(
                        False,
                        checks,
                        "The payment timeout branch does not return the expected queued fallback.",
                        details,
                    )
                details["behavior_check"] = "passed"

                environment = {
                    key: os.environ[key]
                    for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
                    if key in os.environ
                }
                environment.update(
                    {
                        "APP_ENV": "test",
                        "DATABASE_URL": f"sqlite:///{(workspace / 'validation.db').as_posix()}",
                        "MONITOR_SCHEDULER_ENABLED": "false",
                        "PYTHONDONTWRITEBYTECODE": "1",
                        "PYTHONPATH": str(backend_copy),
                    }
                )
                test_files = [
                    str(Path("tests") / test_file.name)
                    for test_file in sorted((backend_copy / "tests").glob("test_*.py"))
                    if test_file.name != "test_validation_pipeline.py"
                ]
                try:
                    test_run = subprocess.run(
                        [sys.executable, "-m", "pytest", *test_files, "-q"],
                        cwd=backend_copy,
                        env=environment,
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=VALIDATION_TIMEOUT_SECONDS,
                    )
                except subprocess.TimeoutExpired:
                    details["unit_test_run"] = "timed_out"
                    return ValidationResult(
                        False,
                        checks,
                        f"Backend tests exceeded the {VALIDATION_TIMEOUT_SECONDS}-second time limit.",
                        details,
                    )
                if test_run.returncode:
                    details["unit_test_run"] = "failed"
                    return ValidationResult(False, checks, "Backend tests failed in the isolated workspace.", details)
                details["unit_test_run"] = "passed"
        except (OSError, subprocess.SubprocessError):
            return ValidationResult(False, checks, "Validation could not complete in the isolated workspace.", details)

        return ValidationResult(
            True,
            checks,
            "Patch applied cleanly, passed static timeout-fallback checks, and backend tests passed in a disposable workspace.",
            details,
        )
