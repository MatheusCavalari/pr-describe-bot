from dataclasses import dataclass

import httpx

GITHUB_API_BASE = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"


@dataclass
class Comment:
    id: int
    body: str


class GitHubClient:
    def __init__(self, installation_token: str):
        self._token = installation_token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }

    async def list_issue_comments(self, repo_full_name: str, pr_number: int) -> list[Comment]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{GITHUB_API_BASE}/repos/{repo_full_name}/issues/{pr_number}/comments",
                headers=self._headers(),
                params={"per_page": 100},
            )
            response.raise_for_status()
            return [Comment(id=c["id"], body=c["body"]) for c in response.json()]

    async def create_comment(self, repo_full_name: str, pr_number: int, body: str) -> None:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{GITHUB_API_BASE}/repos/{repo_full_name}/issues/{pr_number}/comments",
                headers=self._headers(),
                json={"body": body},
            )
            response.raise_for_status()

    async def update_comment(self, repo_full_name: str, comment_id: int, body: str) -> None:
        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{GITHUB_API_BASE}/repos/{repo_full_name}/issues/comments/{comment_id}",
                headers=self._headers(),
                json={"body": body},
            )
            response.raise_for_status()

    async def delete_comment(self, repo_full_name: str, comment_id: int) -> None:
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{GITHUB_API_BASE}/repos/{repo_full_name}/issues/comments/{comment_id}",
                headers=self._headers(),
            )
            response.raise_for_status()
