import httpx
import pytest
import respx

from app.clients.github_client import GitHubClient

REPO = "octocat/hello-world"


@respx.mock
async def test_list_issue_comments_parses_the_response():
    respx.get(f"https://api.github.com/repos/{REPO}/issues/5/comments").mock(
        return_value=httpx.Response(
            200, json=[{"id": 1, "body": "first"}, {"id": 2, "body": "second"}]
        )
    )
    client = GitHubClient("fake-token")

    comments = await client.list_issue_comments(REPO, 5)

    assert [(c.id, c.body) for c in comments] == [(1, "first"), (2, "second")]


@respx.mock
async def test_list_issue_comments_requests_a_full_page():
    route = respx.get(f"https://api.github.com/repos/{REPO}/issues/5/comments").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = GitHubClient("fake-token")

    await client.list_issue_comments(REPO, 5)

    assert route.calls[0].request.url.params["per_page"] == "100"


@respx.mock
async def test_create_comment_posts_the_body():
    route = respx.post(f"https://api.github.com/repos/{REPO}/issues/5/comments").mock(
        return_value=httpx.Response(201, json={"id": 3, "body": "hi"})
    )
    client = GitHubClient("fake-token")

    await client.create_comment(REPO, 5, "hi")

    assert route.calls[0].request.headers["x-github-api-version"] == "2022-11-28"
    assert route.calls[0].request.headers["authorization"] == "Bearer fake-token"


@respx.mock
async def test_update_comment_patches_the_comment_by_id():
    route = respx.patch(f"https://api.github.com/repos/{REPO}/issues/comments/3").mock(
        return_value=httpx.Response(200, json={"id": 3, "body": "updated"})
    )
    client = GitHubClient("fake-token")

    await client.update_comment(REPO, 3, "updated")

    assert route.called


@respx.mock
async def test_delete_comment_deletes_by_id():
    route = respx.delete(f"https://api.github.com/repos/{REPO}/issues/comments/3").mock(
        return_value=httpx.Response(204)
    )
    client = GitHubClient("fake-token")

    await client.delete_comment(REPO, 3)

    assert route.called


@respx.mock
async def test_list_issue_comments_raises_on_error_response():
    respx.get(f"https://api.github.com/repos/{REPO}/issues/5/comments").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    client = GitHubClient("fake-token")

    with pytest.raises(httpx.HTTPStatusError):
        await client.list_issue_comments(REPO, 5)
