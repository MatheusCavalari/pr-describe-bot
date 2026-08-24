import asyncio
import hashlib
import hmac
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

import app.routers.webhook as webhook_module
from app.clients.github_client import CheckRun
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

    def __init__(self, existing_runs: list[CheckRun] | None = None):
        self.runs = list(existing_runs or [])
        self.created: list[tuple[str, str, str, str, str, str]] = []
        self.updated: list[tuple[str, int, str, str, str]] = []
        self._next_id = 1000

    async def list_check_runs_for_ref(self, repo_full_name: str, ref: str, check_name: str) -> list[CheckRun]:
        snapshot = [r for r in self.runs if r.name == check_name]
        await asyncio.sleep(0.01)  # a real HTTP call suspends here
        return snapshot

    async def create_check_run(
        self, repo_full_name: str, name: str, head_sha: str, conclusion: str, title: str, summary: str
    ) -> None:
        await asyncio.sleep(0.01)  # a real HTTP call suspends here
        self.created.append((repo_full_name, name, head_sha, conclusion, title, summary))
        # Mirror real GitHub behavior: once created, a subsequent list call for
        # this check_name would see it. Without this, the concurrency test
        # below can never pass regardless of whether the lock in webhook.py
        # actually serializes requests.
        self._next_id += 1
        self.runs.append(CheckRun(id=self._next_id, name=name))

    async def update_check_run(
        self, repo_full_name: str, check_run_id: int, conclusion: str, title: str, summary: str
    ) -> None:
        self.updated.append((repo_full_name, check_run_id, conclusion, title, summary))


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


async def test_returns_500_when_the_webhook_secret_is_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "github_webhook_secret", "")
    payload = _load_fixture("pull_request_opened.json")
    response = await _post_webhook(payload, signed=False)
    assert response.status_code == 500


async def test_returns_400_for_a_non_json_body():
    transport = ASGITransport(app=app)
    headers = {
        "X-GitHub-Event": "pull_request",
        "Content-Type": "application/json",
        "X-Hub-Signature-256": _sign(b"not json"),
    }
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/webhook", content=b"not json", headers=headers)
    assert response.status_code == 400


async def test_returns_400_for_a_payload_missing_a_required_field(caplog):
    payload = _load_fixture("pull_request_opened.json")
    del payload["pull_request"]["number"]
    with caplog.at_level("WARNING"):
        response = await _post_webhook(payload)
    assert response.status_code == 400
    assert any("Unexpected payload shape" in record.message for record in caplog.records)


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


async def test_creates_both_check_runs_reporting_success_when_nothing_is_wrong(monkeypatch):
    fake_client = FakeGitHubClient(existing_runs=[])
    _use_fake_client(monkeypatch, fake_client)

    payload = _load_fixture("pull_request_opened.json")
    payload["pull_request"]["body"] = "This fixes the pagination cursor off-by-one bug."
    response = await _post_webhook(payload)

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "actions": {"pr-describe-bot/description": "create", "pr-describe-bot/pr-size": "create"},
    }
    assert len(fake_client.created) == 2
    conclusions = {c[1]: c[3] for c in fake_client.created}
    assert conclusions == {"pr-describe-bot/description": "success", "pr-describe-bot/pr-size": "success"}


async def test_creates_a_failing_check_run_when_description_is_missing(monkeypatch):
    fake_client = FakeGitHubClient(existing_runs=[])
    _use_fake_client(monkeypatch, fake_client)

    payload = _load_fixture("pull_request_opened.json")
    response = await _post_webhook(payload)

    assert response.status_code == 200
    description_call = next(c for c in fake_client.created if c[1] == "pr-describe-bot/description")
    assert description_call[3] == "failure"


async def test_updates_an_existing_check_run_instead_of_creating_a_duplicate(monkeypatch):
    existing = CheckRun(id=42, name="pr-describe-bot/description")
    fake_client = FakeGitHubClient(existing_runs=[existing])
    _use_fake_client(monkeypatch, fake_client)

    payload = _load_fixture("pull_request_opened.json")
    payload["pull_request"]["body"] = "This fixes the pagination cursor off-by-one bug."
    response = await _post_webhook(payload)

    assert response.status_code == 200
    assert response.json()["actions"]["pr-describe-bot/description"] == "update"
    assert fake_client.updated[0][1] == 42
    assert fake_client.updated[0][2] == "success"
    assert not any(c[1] == "pr-describe-bot/description" for c in fake_client.created)


async def test_creates_a_failing_check_run_when_the_pr_is_too_large(monkeypatch):
    fake_client = FakeGitHubClient(existing_runs=[])
    _use_fake_client(monkeypatch, fake_client)

    payload = _load_fixture("pull_request_opened.json")
    payload["pull_request"]["body"] = "This fixes the pagination cursor off-by-one bug."
    payload["pull_request"]["additions"] = 400
    payload["pull_request"]["deletions"] = 200
    response = await _post_webhook(payload)

    assert response.status_code == 200
    large_pr_call = next(c for c in fake_client.created if c[1] == "pr-describe-bot/pr-size")
    assert large_pr_call[3] == "failure"
    assert "600" in large_pr_call[4]


async def test_returns_500_when_the_github_client_raises(monkeypatch):
    class FailingClient(FakeGitHubClient):
        async def list_check_runs_for_ref(self, repo_full_name: str, ref: str, check_name: str) -> list[CheckRun]:
            raise RuntimeError("GitHub is down")

    _use_fake_client(monkeypatch, FailingClient())

    payload = _load_fixture("pull_request_opened.json")
    response = await _post_webhook(payload)

    assert response.status_code == 500


async def test_concurrent_webhooks_for_the_same_pr_create_only_one_check_run_per_name(monkeypatch):
    fake_client = FakeGitHubClient(existing_runs=[])
    _use_fake_client(monkeypatch, fake_client)

    payload = _load_fixture("pull_request_opened.json")
    # FakeGitHubClient.list_check_runs_for_ref/create_check_run each suspend
    # (await asyncio.sleep) before returning, so the two requests genuinely
    # interleave under asyncio.gather instead of running back-to-back.
    # Without the per-PR lock in app/routers/webhook.py serializing them,
    # both would see "no check run yet" before either creates one, and both
    # would create a check run for each name.
    responses = await asyncio.gather(_post_webhook(payload), _post_webhook(payload))

    assert all(r.status_code == 200 for r in responses)
    assert len(fake_client.created) == 2  # one per check name, not two per name
