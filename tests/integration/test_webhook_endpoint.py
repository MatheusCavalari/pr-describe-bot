import asyncio
import hashlib
import hmac
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

import app.routers.webhook as webhook_module
from app.clients.github_client import Comment
from app.core.config import settings
from app.main import app

WEBHOOK_SECRET = "test-webhook-secret"
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


def _sign(body: bytes) -> str:
    digest = hmac.new(WEBHOOK_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


class FakeGitHubClient:
    """Records calls instead of hitting the real GitHub API."""

    def __init__(self, existing_comments: list[Comment] | None = None):
        self.existing_comments = existing_comments or []
        self.created: list[tuple[str, int, str]] = []
        self.updated: list[tuple[str, int, str]] = []
        self.deleted: list[tuple[str, int]] = []

    async def list_issue_comments(self, repo_full_name: str, pr_number: int) -> list[Comment]:
        return self.existing_comments

    async def create_comment(self, repo_full_name: str, pr_number: int, body: str) -> None:
        self.created.append((repo_full_name, pr_number, body))
        # Mirror real GitHub behavior: once created, a subsequent list call
        # would see it. Without this, the concurrency test below can never
        # pass regardless of whether the lock in webhook.py actually
        # serializes requests, since list_issue_comments would keep
        # returning a stale empty snapshot.
        self.existing_comments = [*self.existing_comments, Comment(id=len(self.created), body=body)]

    async def update_comment(self, repo_full_name: str, comment_id: int, body: str) -> None:
        self.updated.append((repo_full_name, comment_id, body))

    async def delete_comment(self, repo_full_name: str, comment_id: int) -> None:
        self.deleted.append((repo_full_name, comment_id))


def _use_fake_client(monkeypatch: pytest.MonkeyPatch, fake_client) -> None:
    async def _fake_get_github_client(installation_id: int):
        return fake_client

    monkeypatch.setattr(webhook_module, "get_github_client", _fake_get_github_client)


@pytest.fixture(autouse=True)
def webhook_secret():
    original = settings.github_webhook_secret
    settings.github_webhook_secret = WEBHOOK_SECRET
    yield
    settings.github_webhook_secret = original


async def _post_webhook(body: dict, event: str = "pull_request", signed: bool = True):
    raw = json.dumps(body).encode("utf-8")
    headers = {"X-GitHub-Event": event, "Content-Type": "application/json"}
    if signed:
        headers["X-Hub-Signature-256"] = _sign(raw)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/webhook", content=raw, headers=headers)


async def test_rejects_an_invalid_signature():
    payload = _load_fixture("pull_request_opened.json")
    response = await _post_webhook(payload, signed=False)
    assert response.status_code == 401


async def test_ignores_a_non_pull_request_event():
    payload = _load_fixture("pull_request_opened.json")
    response = await _post_webhook(payload, event="issues")
    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}


async def test_ignores_an_unhandled_action():
    payload = _load_fixture("pull_request_opened.json")
    payload["action"] = "labeled"
    response = await _post_webhook(payload)
    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}


async def test_creates_a_comment_when_description_is_missing_and_none_exists(monkeypatch):
    fake_client = FakeGitHubClient(existing_comments=[])
    _use_fake_client(monkeypatch, fake_client)

    payload = _load_fixture("pull_request_opened.json")
    response = await _post_webhook(payload)

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "action": "create"}
    assert len(fake_client.created) == 1


async def test_deletes_the_comment_once_a_description_is_added(monkeypatch):
    from app.services.reconcile import MARKER

    existing = Comment(id=42, body=f"please add a description\n{MARKER}")
    fake_client = FakeGitHubClient(existing_comments=[existing])
    _use_fake_client(monkeypatch, fake_client)

    payload = _load_fixture("pull_request_opened.json")
    payload["pull_request"]["body"] = "This fixes the pagination cursor off-by-one bug."
    response = await _post_webhook(payload)

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "action": "delete"}
    assert fake_client.deleted == [("octocat/hello-world", 42)]


async def test_returns_500_when_the_github_client_raises(monkeypatch):
    class FailingClient(FakeGitHubClient):
        async def list_issue_comments(self, repo_full_name: str, pr_number: int) -> list[Comment]:
            raise RuntimeError("GitHub is down")

    _use_fake_client(monkeypatch, FailingClient())

    payload = _load_fixture("pull_request_opened.json")
    response = await _post_webhook(payload)

    assert response.status_code == 500


async def test_concurrent_webhooks_for_the_same_pr_create_only_one_comment(monkeypatch):
    fake_client = FakeGitHubClient(existing_comments=[])
    _use_fake_client(monkeypatch, fake_client)

    payload = _load_fixture("pull_request_opened.json")
    # Both requests see the same "no comments yet" snapshot from FakeGitHubClient
    # unless the lock in app/routers/webhook.py actually serializes them.
    responses = await asyncio.gather(_post_webhook(payload), _post_webhook(payload))

    assert all(r.status_code == 200 for r in responses)
    assert len(fake_client.created) == 1
