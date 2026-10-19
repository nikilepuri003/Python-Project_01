from __future__ import annotations

import base64
import binascii
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from app.core.config import get_settings
from app.validation.pipeline import validate_patch_diff

GITHUB_API = "https://api.github.com"
MAX_SOURCE_FILE_BYTES = 500_000


class GitHubIntegrationError(RuntimeError):
    pass


class GitHubService:
    """Create a real draft PR from a validated patch, or report mock mode without fake URLs."""

    def __init__(
        self,
        *,
        token: str | None = None,
        owner: str | None = None,
        repository: str | None = None,
        base_branch: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        settings = get_settings()
        self.token = settings.github_token if token is None else token
        self.owner = settings.github_owner if owner is None else owner
        self.repository = settings.github_repository if repository is None else repository
        self.base_branch = base_branch or settings.github_base_branch
        self.transport = transport

    @property
    def configured(self) -> bool:
        return bool(self.token and self.owner and self.repository and self.base_branch)

    def status(self) -> dict[str, Any]:
        return {
            "mode": "real" if self.configured else "mock",
            "configured": self.configured,
            "repository": f"{self.owner}/{self.repository}" if self.configured else None,
            "base_branch": self.base_branch if self.configured else None,
        }

    def create_draft_pr(
        self,
        *,
        title: str,
        body: str,
        head: str,
        diff: str,
        validation_passed: bool,
        base: str | None = None,
    ) -> dict[str, Any]:
        if not validation_passed:
            raise GitHubIntegrationError("A passing isolated validation result is required before creating a draft PR.")
        file_path = validate_patch_diff(diff)
        if not self.configured:
            return {
                "status": "not_configured",
                "source": "mock",
                "draft": False,
                "url": None,
                "note": "GitHub integration is not configured; no branch or pull request was created.",
            }

        selected_base = base or self.base_branch
        branch = self._validate_branch_name(head)
        api = self._client()
        try:
            base_ref = self._request(
                api,
                "GET",
                f"/repos/{self._repo_path()}/git/ref/heads/{quote(selected_base, safe='')}",
            )
            base_sha = base_ref["object"]["sha"]
            base_commit = self._request(
                api,
                "GET",
                f"/repos/{self._repo_path()}/git/commits/{quote(base_sha, safe='')}",
            )
            content = self._request(
                api,
                "GET",
                f"/repos/{self._repo_path()}/contents/{quote(file_path, safe='/')}",
                params={"ref": selected_base},
            )
            source = self._decode_content(content)
            updated_source = self._apply_diff(file_path, source, diff)
            blob = self._request(
                api,
                "POST",
                f"/repos/{self._repo_path()}/git/blobs",
                json={"content": updated_source, "encoding": "utf-8"},
            )
            tree = self._request(
                api,
                "POST",
                f"/repos/{self._repo_path()}/git/trees",
                json={
                    "base_tree": base_commit["tree"]["sha"],
                    "tree": [{"path": file_path, "mode": "100644", "type": "blob", "sha": blob["sha"]}],
                },
            )
            commit = self._request(
                api,
                "POST",
                f"/repos/{self._repo_path()}/git/commits",
                json={
                    "message": title[:120],
                    "tree": tree["sha"],
                    "parents": [base_sha],
                },
            )
            self._request(
                api,
                "POST",
                f"/repos/{self._repo_path()}/git/refs",
                json={"ref": f"refs/heads/{branch}", "sha": commit["sha"]},
            )
            pull_request = self._request(
                api,
                "POST",
                f"/repos/{self._repo_path()}/pulls",
                json={
                    "title": title[:256],
                    "body": body[:65_000],
                    "head": branch,
                    "base": selected_base,
                    "draft": True,
                },
            )
        except GitHubIntegrationError:
            raise
        except (httpx.HTTPError, KeyError, TypeError, ValueError, binascii.Error) as exc:
            raise GitHubIntegrationError(
                "GitHub draft PR creation failed. No success was reported; check the server-side GitHub configuration and repository permissions."
            ) from exc
        finally:
            api.close()

        pull_url = pull_request.get("html_url")
        pull_number = pull_request.get("number")
        expected_path = f"/{self.owner}/{self.repository}/pull/{pull_number}"
        parsed_url = urlsplit(pull_url) if isinstance(pull_url, str) else None
        if (
            pull_request.get("draft") is not True
            or type(pull_number) is not int
            or parsed_url is None
            or parsed_url.scheme != "https"
            or parsed_url.hostname != "github.com"
            or parsed_url.path.casefold() != expected_path.casefold()
        ):
            raise GitHubIntegrationError("GitHub did not confirm a draft pull request; no PR link is available.")
        return {
            "status": "created",
            "source": "github",
            "draft": True,
            "url": pull_url,
            "number": pull_number,
            "branch": branch,
            "base": selected_base,
            "file_path": file_path,
        }

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=GITHUB_API,
            timeout=httpx.Timeout(10.0, connect=5.0),
            follow_redirects=False,
            transport=self.transport,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    def _repo_path(self) -> str:
        return f"{quote(self.owner, safe='')}/{quote(self.repository, safe='')}"

    @staticmethod
    def _validate_branch_name(branch: str) -> str:
        if (
            not branch
            or len(branch) > 200
            or not branch.startswith("fix/codepulse-incident-")
            or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_/" for character in branch)
            or ".." in branch
            or branch.endswith(("/", "."))
        ):
            raise GitHubIntegrationError("Generated branch name is not permitted.")
        return branch

    @staticmethod
    def _decode_content(payload: dict[str, Any]) -> str:
        if payload.get("encoding") != "base64" or not isinstance(payload.get("content"), str):
            raise GitHubIntegrationError("GitHub did not return a base64 source file.")
        try:
            decoded = base64.b64decode(payload["content"], validate=False)
        except (ValueError, binascii.Error) as exc:
            raise GitHubIntegrationError("GitHub returned invalid source file content.") from exc
        if len(decoded) > MAX_SOURCE_FILE_BYTES:
            raise GitHubIntegrationError("GitHub source file exceeds the allowed size.")
        try:
            return decoded.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GitHubIntegrationError("Only UTF-8 text files may be patched.") from exc

    @staticmethod
    def _apply_diff(file_path: str, source: str, diff: str) -> str:
        approved_path = PurePosixPath(file_path)
        with tempfile.TemporaryDirectory(prefix="codepulse-github-patch-") as temporary_dir:
            workspace = Path(temporary_dir)
            target = workspace / approved_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source, encoding="utf-8")
            try:
                subprocess.run(
                    ["git", "init", "--quiet"],
                    cwd=workspace,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                subprocess.run(
                    ["git", "apply", "--check", "-"],
                    cwd=workspace,
                    input=diff,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                subprocess.run(
                    ["git", "apply", "-"],
                    cwd=workspace,
                    input=diff,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise GitHubIntegrationError(
                    "The validated patch does not apply to the configured repository's current base branch."
                ) from exc
            return target.read_text(encoding="utf-8")

    def _request(self, client: httpx.Client, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise GitHubIntegrationError("GitHub API request failed.") from exc
        if not response.is_success:
            raise GitHubIntegrationError(f"GitHub API rejected the request (HTTP {response.status_code}).")
        try:
            payload = response.json()
        except ValueError as exc:
            raise GitHubIntegrationError("GitHub API returned an invalid response.") from exc
        if not isinstance(payload, dict):
            raise GitHubIntegrationError("GitHub API returned an unexpected response.")
        return payload
