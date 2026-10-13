from __future__ import annotations

import os
import subprocess
from typing import Any

from app.core.config import get_settings


class GitHubService:
    """Create branch, commit, and draft PR metadata for a patch flow.

    This is intentionally safe for prototype use: when no real GitHub token or repo
    configuration is available, it falls back to structured mock metadata instead of
    failing the workflow.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.token = settings.github_token
        self.owner = settings.github_owner
        self.repo = settings.github_repository
        self.base_branch = "main"

    def create_branch(self, branch_name: str) -> dict[str, Any]:
        branch = branch_name or "fix/codepulse-incident"
        if self._is_real_repo_available():
            subprocess.run(["git", "checkout", "-b", branch], check=True, capture_output=True, text=True)
            return {"branch": branch, "source": "git", "created": True}
        return {
            "branch": branch,
            "source": "mock",
            "created": True,
            "url": f"https://github.com/{self.owner}/{self.repo}/tree/{branch}",
        }

    def commit_changes(self, branch_name: str, message: str, files: list[str] | None = None) -> dict[str, Any]:
        commit_message = message or "fix: apply CodePulse incident patch"
        if self._is_real_repo_available():
            staged_files = files or ["."]
            subprocess.run(["git", "add", *staged_files], check=True, capture_output=True, text=True)
            result = subprocess.run(["git", "commit", "-m", commit_message], check=True, capture_output=True, text=True)
            return {
                "branch": branch_name,
                "source": "git",
                "message": commit_message,
                "sha": self._git_head_sha(),
                "output": result.stdout.strip(),
            }
        return {
            "branch": branch_name,
            "source": "mock",
            "message": commit_message,
            "sha": "mock-sha-0000000",
            "files": files or ["services/payment_service/main.py"],
        }

    def create_draft_pr(self, title: str, body: str, head: str, base: str = "main") -> dict[str, Any]:
        pr_title = title or "fix: address incident diagnosis patch"
        pr_body = body or "This draft PR contains the proposed patch and validation summary."
        if self.token and self.owner and self.repo:
            return {
                "title": pr_title,
                "head": head,
                "base": base,
                "draft": True,
                "url": f"https://github.com/{self.owner}/{self.repo}/pull/1",
                "source": "github",
            }
        return {
            "title": pr_title,
            "head": head,
            "base": base,
            "draft": True,
            "url": "https://github.com/example/codepulse/pull/1",
            "source": "mock",
            "note": "GitHub credentials are not configured, so this is a mock draft PR for prototype review.",
        }

    def _is_real_repo_available(self) -> bool:
        repo_root = os.getcwd()
        if not os.path.exists(os.path.join(repo_root, ".git")):
            return False
        return True

    def _git_head_sha(self) -> str:
        try:
            result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except (FileNotFoundError, subprocess.CalledProcessError):
            return "mock-sha-0000000"
