import json

import httpx
import pytest
import respx

from app.clients.github_client import GitHubClient

REPO = "octocat/hello-world"
SHA = "abc123"


@respx.mock
async def test_list_check_runs_for_ref_parses_the_response():
    respx.get(f"https://api.github.com/repos/{REPO}/commits/{SHA}/check-runs").mock(
        return_value=httpx.Response(
            200,
            json={
                "check_runs": [
                    {"id": 1, "name": "pr-describe-bot/description"},
                    {"id": 2, "name": "pr-describe-bot/pr-size"},
                ]
            },
        )
    )
    client = GitHubClient("fake-token")

    runs = await client.list_check_runs_for_ref(REPO, SHA, "pr-describe-bot/description")

    assert [(r.id, r.name) for r in runs] == [
        (1, "pr-describe-bot/description"),
        (2, "pr-describe-bot/pr-size"),
    ]


@respx.mock
async def test_list_check_runs_for_ref_filters_by_check_name_and_paginates():
    route = respx.get(f"https://api.github.com/repos/{REPO}/commits/{SHA}/check-runs").mock(
        return_value=httpx.Response(200, json={"check_runs": []})
    )
    client = GitHubClient("fake-token")

    await client.list_check_runs_for_ref(REPO, SHA, "pr-describe-bot/description")

    params = route.calls[0].request.url.params
    assert params["check_name"] == "pr-describe-bot/description"
    assert params["per_page"] == "100"


@respx.mock
async def test_create_check_run_posts_the_expected_body():
    route = respx.post(f"https://api.github.com/repos/{REPO}/check-runs").mock(
        return_value=httpx.Response(201, json={"id": 3})
    )
    client = GitHubClient("fake-token")

    await client.create_check_run(REPO, "pr-describe-bot/description", SHA, "failure", "title", "summary")

    request = route.calls[0].request
    assert request.headers["x-github-api-version"] == "2022-11-28"
    assert request.headers["authorization"] == "Bearer fake-token"
    body = json.loads(request.content)
    assert body == {
        "name": "pr-describe-bot/description",
        "head_sha": SHA,
        "status": "completed",
        "conclusion": "failure",
        "output": {"title": "title", "summary": "summary"},
    }


@respx.mock
async def test_update_check_run_patches_by_id():
    route = respx.patch(f"https://api.github.com/repos/{REPO}/check-runs/3").mock(
        return_value=httpx.Response(200, json={"id": 3})
    )
    client = GitHubClient("fake-token")

    await client.update_check_run(REPO, 3, "success", "title", "summary")

    assert route.called


@respx.mock
async def test_list_check_runs_for_ref_raises_on_error_response():
    respx.get(f"https://api.github.com/repos/{REPO}/commits/{SHA}/check-runs").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    client = GitHubClient("fake-token")

    with pytest.raises(httpx.HTTPStatusError):
        await client.list_check_runs_for_ref(REPO, SHA, "pr-describe-bot/description")
