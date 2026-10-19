import base64
import json

import httpx

from app.github.service import GitHubService


def test_unconfigured_github_reports_mock_without_fake_pr_url() -> None:
    service = GitHubService(token="", owner="", repository="")

    result = service.create_draft_pr(
        title="fix: demo payment timeout",
        body="Review the demo fix.",
        head="fix/codepulse-incident-1-12345678",
        diff="--- a/services/payment_service/main.py\n"
        "+++ b/services/payment_service/main.py\n"
        "@@ -1 +1 @@\n-old\n+new\n",
        validation_passed=True,
    )

    assert service.status()["mode"] == "mock"
    assert result == {
        "status": "not_configured",
        "source": "mock",
        "draft": False,
        "url": None,
        "note": "GitHub integration is not configured; no branch or pull request was created.",
    }


def test_github_service_creates_real_draft_pr_through_api_only_after_validation() -> None:
    source = "old\n"
    calls: list[tuple[str, str]] = []

    def github_api(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        assert request.headers["Authorization"] == "Bearer server-token"
        path = request.url.path
        if request.method == "GET" and path.endswith("/git/ref/heads/main"):
            return httpx.Response(200, json={"object": {"sha": "base-sha"}})
        if request.method == "GET" and path.endswith("/git/commits/base-sha"):
            return httpx.Response(200, json={"tree": {"sha": "base-tree"}})
        if request.method == "GET" and path.endswith("/contents/services/payment_service/main.py"):
            return httpx.Response(
                200,
                json={"encoding": "base64", "content": base64.b64encode(source.encode()).decode()},
            )
        if request.method == "POST" and path.endswith("/git/blobs"):
            assert json.loads(request.content) == {"content": "new\n", "encoding": "utf-8"}
            return httpx.Response(201, json={"sha": "blob-sha"})
        if request.method == "POST" and path.endswith("/git/trees"):
            tree = json.loads(request.content)
            assert tree["base_tree"] == "base-tree"
            assert tree["tree"][0]["path"] == "services/payment_service/main.py"
            return httpx.Response(201, json={"sha": "tree-sha"})
        if request.method == "POST" and path.endswith("/git/commits"):
            commit = json.loads(request.content)
            assert commit["parents"] == ["base-sha"]
            return httpx.Response(201, json={"sha": "commit-sha"})
        if request.method == "POST" and path.endswith("/git/refs"):
            assert json.loads(request.content)["sha"] == "commit-sha"
            return httpx.Response(201, json={"ref": "refs/heads/fix/branch"})
        if request.method == "POST" and path.endswith("/pulls"):
            pr = json.loads(request.content)
            assert pr["draft"] is True
            assert pr["head"] == "fix/codepulse-incident-9-12345678"
            return httpx.Response(201, json={"number": 42, "draft": True, "html_url": "https://github.com/org/repo/pull/42"})
        return httpx.Response(404, json={"message": "unexpected"})

    service = GitHubService(
        token="server-token",
        owner="org",
        repository="repo",
        base_branch="main",
        transport=httpx.MockTransport(github_api),
    )
    diff = (
        "--- a/services/payment_service/main.py\n"
        "+++ b/services/payment_service/main.py\n"
        "@@ -1 +1 @@\n-old\n+new\n"
    )
    result = service.create_draft_pr(
        title="fix: payment timeout",
        body="Please review.",
        head="fix/codepulse-incident-9-12345678",
        diff=diff,
        validation_passed=True,
    )

    assert result["status"] == "created"
    assert result["source"] == "github"
    assert result["draft"] is True
    assert result["number"] == 42
    assert result["url"] == "https://github.com/org/repo/pull/42"
    assert [method for method, _ in calls].count("POST") == 5


def test_github_service_refuses_unvalidated_or_unsafe_patches() -> None:
    service = GitHubService(token="token", owner="org", repository="repo")
    try:
        service.create_draft_pr(
            title="fix",
            body="",
            head="fix/codepulse-incident-1-12345678",
            diff="--- a/services/payment_service/main.py\n"
            "+++ b/services/payment_service/main.py\n"
            "@@ -1 +1 @@\n-old\n+new\n",
            validation_passed=False,
        )
    except RuntimeError as exc:
        assert "validation" in str(exc)
    else:
        raise AssertionError("Unvalidated patch was accepted.")

    try:
        service.create_draft_pr(
            title="fix",
            body="",
            head="fix/codepulse-incident-1-12345678",
            diff="--- a/backend/app/main.py\n+++ b/backend/app/main.py\n@@ -1 +1 @@\n-old\n+new\n",
            validation_passed=True,
        )
    except ValueError as exc:
        assert "approved demo service" in str(exc)
    else:
        raise AssertionError("Unsafe target path was accepted.")
