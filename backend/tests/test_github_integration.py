from app.github.service import GitHubService


def test_github_service_creates_branch_metadata() -> None:
    service = GitHubService()
    result = service.create_branch("fix/codepulse-incident")

    assert result["branch"] == "fix/codepulse-incident"
    assert result["created"] is True
    assert "source" in result


def test_github_service_creates_draft_pr_metadata() -> None:
    service = GitHubService()
    result = service.create_draft_pr(
        title="fix: payment timeout patch",
        body="This is a prototype draft PR for review.",
        head="fix/codepulse-incident",
    )

    assert result["draft"] is True
    assert result["head"] == "fix/codepulse-incident"
    assert "url" in result
