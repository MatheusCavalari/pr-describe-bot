import logging
from dataclasses import dataclass

import httpx

GITHUB_API_BASE = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"

logger = logging.getLogger(__name__)


@dataclass
class CheckRun:
    id: int
    name: str


class GitHubClient:
    def __init__(self, installation_token: str):
        self._token = installation_token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }

    async def list_check_runs_for_ref(
        self, repo_full_name: str, ref: str, check_name: str
    ) -> list[CheckRun]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{GITHUB_API_BASE}/repos/{repo_full_name}/commits/{ref}/check-runs",
                headers=self._headers(),
                params={"check_name": check_name, "per_page": 100},
            )
            response.raise_for_status()
            return [
                CheckRun(id=r["id"], name=r["name"]) for r in response.json()["check_runs"]
            ]

    async def create_check_run(
        self, repo_full_name: str, name: str, head_sha: str, conclusion: str, title: str, summary: str
    ) -> None:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{GITHUB_API_BASE}/repos/{repo_full_name}/check-runs",
                headers=self._headers(),
                json={
                    "name": name,
                    "head_sha": head_sha,
                    "status": "completed",
                    "conclusion": conclusion,
                    "output": {"title": title, "summary": summary},
                },
            )
            response.raise_for_status()
            logger.warning("create_check_run response: status=%s body=%s", response.status_code, response.text)

    async def update_check_run(
        self, repo_full_name: str, check_run_id: int, conclusion: str, title: str, summary: str
    ) -> None:
        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{GITHUB_API_BASE}/repos/{repo_full_name}/check-runs/{check_run_id}",
                headers=self._headers(),
                json={
                    "status": "completed",
                    "conclusion": conclusion,
                    "output": {"title": title, "summary": summary},
                },
            )
            response.raise_for_status()
