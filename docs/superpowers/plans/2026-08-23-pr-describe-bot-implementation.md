# PR Describe Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A GitHub App that comments on a PR when it's missing a description, keeps that comment in sync as the PR is edited, and removes it once fixed.

**Architecture:** Single FastAPI service, no database, no frontend. A `POST /webhook` endpoint verifies GitHub's HMAC signature, authenticates as the GitHub App (JWT → installation token), evaluates the description rule against the PR body, and reconciles a single marker-tagged comment (create/update/delete/no-op) via the GitHub REST API. An in-process per-PR lock serializes concurrent webhook deliveries for the same PR.

**Tech Stack:** Python 3.12, FastAPI, httpx (async), PyJWT + cryptography (RS256 App JWT), pydantic-settings. Dev: pytest, pytest-asyncio, respx (mocks httpx calls), ruff.

## Global Constraints

- No database, no ORM, no migrations — every check re-reads current PR state per webhook delivery.
- Every outgoing GitHub API request must send `X-GitHub-Api-Version: 2022-11-28`.
- Webhook signature check must use `hmac.compare_digest` (constant-time), never `==`.
- A failed GitHub API call during reconcile must surface as an HTTP 500 from `/webhook` (GitHub retries failed deliveries) — never swallowed silently.
- An unrecognized/ignored webhook event or `action` must still return HTTP 200 immediately.
- The reconcile lock is per `(repository_full_name, pr_number)`, in-process only (`asyncio.Lock`), correct for a single running instance.
- Line length 100 (ruff), `pytest-asyncio` in `auto` mode — mirror the `pyproject.toml` conventions below exactly.

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `app/__init__.py`
- Create: `app/main.py`
- Create: `app/core/__init__.py`
- Create: `app/core/config.py`
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/unit/test_main.py`
- Create: `Dockerfile`
- Create: `Makefile`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: `app.core.config.settings` — a `Settings` instance with `github_app_id: str`, `github_app_private_key: str`, `github_webhook_secret: str`, all defaulting to `""` (so tests never need real secrets).
- Produces: `app.main.app` — the FastAPI instance, with `GET /healthz` returning `{"status": "ok"}`.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "pr-describe-bot"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "httpx>=0.27",
    "pydantic-settings>=2.6",
    "pyjwt[crypto]>=2.9",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "respx>=0.21",
    "ruff>=0.7",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["app*"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "session"
asyncio_default_test_loop_scope = "session"
testpaths = ["tests"]

[tool.ruff]
line-length = 100

[tool.ruff.lint.per-file-ignores]
"app/routers/*.py" = ["B008"]
```

- [ ] **Step 2: Write `app/core/config.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    github_app_id: str = ""
    github_app_private_key: str = ""
    github_webhook_secret: str = ""

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
```

- [ ] **Step 3: Write `app/main.py`**

```python
from fastapi import FastAPI

app = FastAPI(title="PR Describe Bot")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: Write the failing test**

`tests/unit/test_main.py`:

```python
from httpx import ASGITransport, AsyncClient

from app.main import app


async def test_healthz_returns_ok():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 5: Install and run**

```bash
python -m pip install -e ".[dev]"
python -m pytest tests/unit -v
```

Expected: PASS (1 passed).

- [ ] **Step 6: Write `Dockerfile`**

```dockerfile
FROM python:3.12-slim AS base
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir .
COPY app ./app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 7: Write `Makefile`**

```makefile
run:
	uvicorn app.main:app --reload

test:
	pytest tests/unit -v

lint:
	ruff check .
```

- [ ] **Step 8: Write `.env.example`**

```
GITHUB_APP_ID=
GITHUB_APP_PRIVATE_KEY=
GITHUB_WEBHOOK_SECRET=
```

- [ ] **Step 9: Write `.gitignore`**

```
__pycache__/
*.pyc
.env
.venv/
venv/
*.egg-info/
.pytest_cache/
.ruff_cache/
```

- [ ] **Step 10: Write `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [master]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: ruff check .
      - run: pytest tests/unit -v
```

- [ ] **Step 11: Commit**

```bash
git add .
git commit -m "chore: project scaffolding, healthz endpoint, CI"
```

---

### Task 2: Webhook signature verification

**Files:**
- Create: `app/core/signature.py`
- Test: `tests/unit/test_signature.py`

**Interfaces:**
- Produces: `verify_signature(payload: bytes, signature_header: str | None, secret: str) -> bool`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_signature.py`:

```python
import hashlib
import hmac

from app.core.signature import verify_signature

SECRET = "test-secret"
BODY = b'{"action": "opened"}'


def _sign(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_accepts_a_valid_signature():
    assert verify_signature(BODY, _sign(BODY, SECRET), SECRET) is True


def test_rejects_a_signature_signed_with_the_wrong_secret():
    assert verify_signature(BODY, _sign(BODY, "wrong-secret"), SECRET) is False


def test_rejects_a_signature_for_a_different_body():
    wrong_body_signature = _sign(b'{"action": "closed"}', SECRET)
    assert verify_signature(BODY, wrong_body_signature, SECRET) is False


def test_rejects_a_missing_header():
    assert verify_signature(BODY, None, SECRET) is False


def test_rejects_a_header_without_the_sha256_prefix():
    digest = hmac.new(SECRET.encode("utf-8"), BODY, hashlib.sha256).hexdigest()
    assert verify_signature(BODY, digest, SECRET) is False
```

- [ ] **Step 2: Run, confirm it fails**

```bash
pytest tests/unit/test_signature.py -v
```

Expected: FAIL (`ModuleNotFoundError` / `ImportError` — `app.core.signature` doesn't exist yet).

- [ ] **Step 3: Write `app/core/signature.py`**

```python
import hashlib
import hmac


def verify_signature(payload: bytes, signature_header: str | None, secret: str) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)
```

- [ ] **Step 4: Run, confirm it passes**

```bash
pytest tests/unit/test_signature.py -v
```

Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add app/core/signature.py tests/unit/test_signature.py
git commit -m "feat: webhook signature verification"
```

---

### Task 3: GitHub App authentication (JWT + installation token)

**Files:**
- Create: `app/core/github_auth.py`
- Test: `tests/unit/test_github_auth.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `create_app_jwt(app_id: str, private_key_pem: str) -> str`; `async get_installation_token(app_jwt: str, installation_id: int) -> str`.

**Note on the test private key:** RS256 needs a real (but throwaway) RSA key pair. Generate one once and paste the PEM literal into the test file — do not generate it dynamically per test run, so failures are reproducible and the test doesn't depend on the `cryptography` key-generation path being exercised at test time (that's not what's under test).

- [ ] **Step 1: Generate a throwaway test RSA key**

```bash
python -c "
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
pem = key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode()
print(pem)
"
```

Copy the output (including `-----BEGIN PRIVATE KEY-----` / `-----END PRIVATE KEY-----`) into `TEST_PRIVATE_KEY` in the test file below.

- [ ] **Step 2: Write the failing tests**

`tests/unit/test_github_auth.py`:

```python
import time

import httpx
import jwt
import pytest
import respx

from app.core.github_auth import create_app_jwt, get_installation_token

# Throwaway RSA key, generated once for tests only -- never a real App key.
TEST_PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
PASTE_THE_GENERATED_PEM_HERE
-----END PRIVATE KEY-----"""

TEST_PUBLIC_KEY_PEM = None  # derived in a fixture below if needed for decode verification


def test_create_app_jwt_has_expected_claims():
    token = create_app_jwt("12345", TEST_PRIVATE_KEY)
    decoded = jwt.decode(token, options={"verify_signature": False})
    assert decoded["iss"] == "12345"
    now = int(time.time())
    assert decoded["iat"] <= now
    assert decoded["exp"] > now


@respx.mock
async def test_get_installation_token_returns_the_token_from_the_response():
    route = respx.post(
        "https://api.github.com/app/installations/999/access_tokens"
    ).mock(return_value=httpx.Response(201, json={"token": "ghs_faketoken"}))

    token = await get_installation_token("fake-app-jwt", 999)

    assert token == "ghs_faketoken"
    assert route.called
    sent_headers = route.calls[0].request.headers
    assert sent_headers["authorization"] == "Bearer fake-app-jwt"
    assert sent_headers["x-github-api-version"] == "2022-11-28"


@respx.mock
async def test_get_installation_token_raises_on_error_response():
    respx.post("https://api.github.com/app/installations/999/access_tokens").mock(
        return_value=httpx.Response(401, json={"message": "Bad credentials"})
    )

    with pytest.raises(httpx.HTTPStatusError):
        await get_installation_token("fake-app-jwt", 999)
```

- [ ] **Step 3: Run, confirm it fails**

```bash
pytest tests/unit/test_github_auth.py -v
```

Expected: FAIL (`ModuleNotFoundError` — `app.core.github_auth` doesn't exist yet).

- [ ] **Step 4: Write `app/core/github_auth.py`**

```python
import time

import httpx
import jwt

GITHUB_API_BASE = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"


def create_app_jwt(app_id: str, private_key_pem: str) -> str:
    now = int(time.time())
    payload = {
        "iat": now - 60,  # allow for clock drift with GitHub's servers
        "exp": now + 600,
        "iss": app_id,
    }
    return jwt.encode(payload, private_key_pem, algorithm="RS256")


async def get_installation_token(app_jwt: str, installation_id: int) -> str:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{GITHUB_API_BASE}/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            },
        )
        response.raise_for_status()
        return response.json()["token"]
```

- [ ] **Step 5: Run, confirm it passes**

```bash
pytest tests/unit/test_github_auth.py -v
```

Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add app/core/github_auth.py tests/unit/test_github_auth.py
git commit -m "feat: GitHub App JWT and installation token exchange"
```

---

### Task 4: GitHub API client (comment operations)

**Files:**
- Create: `app/clients/__init__.py`
- Create: `app/clients/github_client.py`
- Test: `tests/unit/test_github_client.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (takes a raw installation token string).
- Produces: `Comment` (dataclass: `id: int`, `body: str`); `GitHubClient(installation_token: str)` with `async list_issue_comments(repo_full_name: str, pr_number: int) -> list[Comment]`, `async create_comment(repo_full_name: str, pr_number: int, body: str) -> None`, `async update_comment(repo_full_name: str, comment_id: int, body: str) -> None`, `async delete_comment(repo_full_name: str, comment_id: int) -> None`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_github_client.py`:

```python
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
```

- [ ] **Step 2: Run, confirm it fails**

```bash
pytest tests/unit/test_github_client.py -v
```

Expected: FAIL (`ModuleNotFoundError` — `app.clients.github_client` doesn't exist yet).

- [ ] **Step 3: Write `app/clients/github_client.py`**

```python
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
```

- [ ] **Step 4: Run, confirm it passes**

```bash
pytest tests/unit/test_github_client.py -v
```

Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add app/clients tests/unit/test_github_client.py
git commit -m "feat: GitHub API client for comment operations"
```

---

### Task 5: Description-missing rule

**Files:**
- Create: `app/services/__init__.py`
- Create: `app/services/description_check.py`
- Test: `tests/unit/test_description_check.py`

**Interfaces:**
- Produces: `is_description_missing(body: str | None) -> bool`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_description_check.py`:

```python
from app.services.description_check import is_description_missing


def test_none_body_is_missing():
    assert is_description_missing(None) is True


def test_empty_string_is_missing():
    assert is_description_missing("") is True


def test_whitespace_only_is_missing():
    assert is_description_missing("   \n\t  ") is True


def test_short_text_is_missing():
    assert is_description_missing("fixed it") is True


def test_only_html_comment_is_missing():
    body = "<!-- This is an auto-generated PR template. Please fill me in! -->"
    assert is_description_missing(body) is True


def test_long_enough_real_text_is_not_missing():
    body = "This PR fixes the off-by-one error in the pagination cursor calculation."
    assert is_description_missing(body) is False


def test_html_comment_is_stripped_before_measuring_length():
    body = (
        "<!-- template boilerplate that should not count -->\n"
        "Short."
    )
    assert is_description_missing(body) is True
```

- [ ] **Step 2: Run, confirm it fails**

```bash
pytest tests/unit/test_description_check.py -v
```

Expected: FAIL (`ModuleNotFoundError` — `app.services.description_check` doesn't exist yet).

- [ ] **Step 3: Write `app/services/description_check.py`**

```python
import re

MIN_DESCRIPTION_LENGTH = 20
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def is_description_missing(body: str | None) -> bool:
    if body is None:
        return True
    stripped = _HTML_COMMENT_RE.sub("", body).strip()
    return len(stripped) < MIN_DESCRIPTION_LENGTH
```

- [ ] **Step 4: Run, confirm it passes**

```bash
pytest tests/unit/test_description_check.py -v
```

Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add app/services/description_check.py tests/unit/test_description_check.py
git commit -m "feat: description-missing rule"
```

---

### Task 6: Marker comment lookup and reconcile decision

**Files:**
- Create: `app/services/reconcile.py`
- Test: `tests/unit/test_reconcile.py`

**Interfaces:**
- Consumes: `Comment` from `app.clients.github_client` (Task 4).
- Produces: `MARKER: str`; `NAG_MESSAGE: str` (ends with `MARKER`); `Action` (`Enum`: `NOOP`, `CREATE`, `UPDATE`, `DELETE`); `ReconcileResult` (dataclass: `action: Action`, `comment_id: int | None = None`); `find_marker_comment(comments: list[Comment]) -> Comment | None`; `decide_action(description_missing: bool, existing_comment: Comment | None) -> ReconcileResult`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_reconcile.py`:

```python
from app.clients.github_client import Comment
from app.services.reconcile import (
    MARKER,
    NAG_MESSAGE,
    Action,
    decide_action,
    find_marker_comment,
)


def test_nag_message_contains_the_marker():
    assert MARKER in NAG_MESSAGE


def test_find_marker_comment_returns_none_when_absent():
    comments = [Comment(id=1, body="just chatting"), Comment(id=2, body="+1")]
    assert find_marker_comment(comments) is None


def test_find_marker_comment_finds_the_one_with_the_marker():
    target = Comment(id=2, body=f"please add a description\n{MARKER}")
    comments = [Comment(id=1, body="unrelated"), target]
    assert find_marker_comment(comments) is target


def test_missing_description_and_no_existing_comment_creates():
    result = decide_action(description_missing=True, existing_comment=None)
    assert result.action == Action.CREATE
    assert result.comment_id is None


def test_missing_description_and_existing_comment_updates():
    existing = Comment(id=7, body=f"old message\n{MARKER}")
    result = decide_action(description_missing=True, existing_comment=existing)
    assert result.action == Action.UPDATE
    assert result.comment_id == 7


def test_description_present_and_existing_comment_deletes():
    existing = Comment(id=7, body=f"old message\n{MARKER}")
    result = decide_action(description_missing=False, existing_comment=existing)
    assert result.action == Action.DELETE
    assert result.comment_id == 7


def test_description_present_and_no_existing_comment_is_noop():
    result = decide_action(description_missing=False, existing_comment=None)
    assert result.action == Action.NOOP
    assert result.comment_id is None
```

- [ ] **Step 2: Run, confirm it fails**

```bash
pytest tests/unit/test_reconcile.py -v
```

Expected: FAIL (`ModuleNotFoundError` — `app.services.reconcile` doesn't exist yet).

- [ ] **Step 3: Write `app/services/reconcile.py`**

```python
from dataclasses import dataclass
from enum import Enum

from app.clients.github_client import Comment

MARKER = "<!-- pr-describe-bot:marker -->"

NAG_MESSAGE = (
    "👋 This PR doesn't have a description yet. Mind adding one? "
    "It helps reviewers (and future you) understand the *why* behind the change.\n\n"
    + MARKER
)


class Action(Enum):
    NOOP = "noop"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


@dataclass
class ReconcileResult:
    action: Action
    comment_id: int | None = None


def find_marker_comment(comments: list[Comment]) -> Comment | None:
    for comment in comments:
        if MARKER in comment.body:
            return comment
    return None


def decide_action(description_missing: bool, existing_comment: Comment | None) -> ReconcileResult:
    if description_missing:
        if existing_comment is None:
            return ReconcileResult(Action.CREATE)
        return ReconcileResult(Action.UPDATE, existing_comment.id)
    if existing_comment is not None:
        return ReconcileResult(Action.DELETE, existing_comment.id)
    return ReconcileResult(Action.NOOP)
```

- [ ] **Step 4: Run, confirm it passes**

```bash
pytest tests/unit/test_reconcile.py -v
```

Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add app/services/reconcile.py tests/unit/test_reconcile.py
git commit -m "feat: marker comment lookup and reconcile decision logic"
```

---

### Task 7: Per-PR lock registry

**Files:**
- Create: `app/core/locks.py`
- Test: `tests/unit/test_locks.py`

**Interfaces:**
- Produces: `get_lock(repo_full_name: str, pr_number: int) -> asyncio.Lock`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_locks.py`:

```python
from app.core.locks import get_lock


def test_same_repo_and_pr_number_returns_the_same_lock():
    lock_a = get_lock("octocat/hello-world", 5)
    lock_b = get_lock("octocat/hello-world", 5)
    assert lock_a is lock_b


def test_different_pr_number_returns_a_different_lock():
    lock_a = get_lock("octocat/hello-world", 5)
    lock_b = get_lock("octocat/hello-world", 6)
    assert lock_a is not lock_b


def test_different_repo_returns_a_different_lock():
    lock_a = get_lock("octocat/hello-world", 5)
    lock_b = get_lock("octocat/other-repo", 5)
    assert lock_a is not lock_b
```

- [ ] **Step 2: Run, confirm it fails**

```bash
pytest tests/unit/test_locks.py -v
```

Expected: FAIL (`ModuleNotFoundError` — `app.core.locks` doesn't exist yet).

- [ ] **Step 3: Write `app/core/locks.py`**

```python
import asyncio
import collections

# Grows by one entry per distinct (repo, pr_number) ever seen by this process
# and is never evicted -- acceptable for v1's traffic scale. Revisit with an
# LRU or TTL eviction if this ever becomes a real memory concern.
_locks: dict[tuple[str, int], asyncio.Lock] = collections.defaultdict(asyncio.Lock)


def get_lock(repo_full_name: str, pr_number: int) -> asyncio.Lock:
    return _locks[(repo_full_name, pr_number)]
```

- [ ] **Step 4: Run, confirm it passes**

```bash
pytest tests/unit/test_locks.py -v
```

Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add app/core/locks.py tests/unit/test_locks.py
git commit -m "feat: per-(repo, pr) lock registry"
```

---

### Task 8: Webhook endpoint (wires everything together)

**Files:**
- Create: `app/routers/__init__.py`
- Create: `app/routers/webhook.py`
- Modify: `app/main.py` (include the router)
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/fixtures/pull_request_opened.json`
- Create: `tests/integration/test_webhook_endpoint.py`

**Interfaces:**
- Consumes: `verify_signature` (Task 2), `create_app_jwt`/`get_installation_token` (Task 3), `GitHubClient` (Task 4), `is_description_missing` (Task 5), `find_marker_comment`/`decide_action`/`Action`/`NAG_MESSAGE` (Task 6), `get_lock` (Task 7).
- Produces: `POST /webhook` — returns `{"status": "ignored"}` (200) for unhandled events/actions, `{"status": "ok", "action": <action>}` (200) on success, 401 on bad signature, 400 on malformed payload, 500 on a GitHub API failure during reconcile.

**Testability note:** the GitHub client construction (JWT → installation token → `GitHubClient`) lives in a module-level function, `get_github_client`, in `app/routers/webhook.py`. Integration tests replace it with pytest's `monkeypatch.setattr(webhook_module, "get_github_client", ...)` to inject a fake client instead of hitting real GitHub auth endpoints. (FastAPI's `Depends`/`dependency_overrides` mechanism isn't used here on purpose: the client can only be constructed once `installation_id` is known from the already-parsed webhook body, and re-declaring it as a `Depends` would mean parsing that body a second time — `monkeypatch` on the plain function is simpler and just as explicit.)

- [ ] **Step 1: Write the example webhook payload fixture**

`tests/integration/fixtures/pull_request_opened.json`:

```json
{
  "action": "opened",
  "number": 5,
  "pull_request": {
    "number": 5,
    "body": null
  },
  "repository": {
    "full_name": "octocat/hello-world"
  },
  "installation": {
    "id": 999
  }
}
```

- [ ] **Step 2: Write the failing integration tests**

`tests/integration/test_webhook_endpoint.py`:

```python
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
```

- [ ] **Step 3: Run, confirm it fails**

```bash
pytest tests/integration -v
```

Expected: FAIL (`ModuleNotFoundError` — `app.routers.webhook` doesn't exist yet).

- [ ] **Step 4: Write `app/routers/webhook.py`**

```python
import logging

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.clients.github_client import GitHubClient
from app.core.config import settings
from app.core.github_auth import create_app_jwt, get_installation_token
from app.core.locks import get_lock
from app.core.signature import verify_signature
from app.services.description_check import is_description_missing
from app.services.reconcile import NAG_MESSAGE, Action, decide_action, find_marker_comment

logger = logging.getLogger(__name__)

router = APIRouter()

HANDLED_ACTIONS = {"opened", "edited", "synchronize", "reopened"}


async def get_github_client(installation_id: int) -> GitHubClient:
    app_jwt = create_app_jwt(settings.github_app_id, settings.github_app_private_key)
    token = await get_installation_token(app_jwt, installation_id)
    return GitHubClient(token)


@router.post("/webhook")
async def receive_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
) -> dict[str, str]:
    raw_body = await request.body()
    if not verify_signature(raw_body, x_hub_signature_256, settings.github_webhook_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid signature")

    if x_github_event != "pull_request":
        return {"status": "ignored"}

    payload = await request.json()
    action = payload.get("action")
    if action not in HANDLED_ACTIONS:
        return {"status": "ignored"}

    try:
        installation_id = payload["installation"]["id"]
        pr_number = payload["pull_request"]["number"]
        pr_body = payload["pull_request"]["body"]
        repo_full_name = payload["repository"]["full_name"]
    except KeyError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unexpected payload shape")

    lock = get_lock(repo_full_name, pr_number)
    async with lock:
        try:
            github_client = await get_github_client(installation_id)
            comments = await github_client.list_issue_comments(repo_full_name, pr_number)
            existing = find_marker_comment(comments)
            result = decide_action(is_description_missing(pr_body), existing)

            if result.action == Action.CREATE:
                await github_client.create_comment(repo_full_name, pr_number, NAG_MESSAGE)
            elif result.action == Action.UPDATE:
                await github_client.update_comment(repo_full_name, result.comment_id, NAG_MESSAGE)
            elif result.action == Action.DELETE:
                await github_client.delete_comment(repo_full_name, result.comment_id)
        except Exception:
            logger.exception(
                "Failed to reconcile PR comment for %s#%s", repo_full_name, pr_number
            )
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="reconcile failed")

    return {"status": "ok", "action": result.action.value}
```

- [ ] **Step 5: Wire the router into `app/main.py`**

```python
from fastapi import FastAPI

from app.routers import webhook

app = FastAPI(title="PR Describe Bot")
app.include_router(webhook.router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 6: Run, confirm it passes**

```bash
pytest tests/unit tests/integration -v
```

Expected: PASS (all tests, unit + integration).

- [ ] **Step 7: Lint**

```bash
ruff check .
```

Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add app/routers app/main.py tests/integration
git commit -m "feat: webhook endpoint wiring signature, auth, and reconcile"
```

---

### Task 9: Deployment config and README

**Files:**
- Create: `render.yaml`
- Create: `README.md`

**Interfaces:**
- Consumes: nothing new — documents how to actually stand this up.

- [ ] **Step 1: Write `render.yaml`**

```yaml
services:
  - type: web
    name: pr-describe-bot
    runtime: docker
    dockerfilePath: ./Dockerfile
    dockerContext: .
    plan: free
    healthCheckPath: /healthz
    envVars:
      - key: GITHUB_APP_ID
        sync: false
      - key: GITHUB_APP_PRIVATE_KEY
        sync: false
      - key: GITHUB_WEBHOOK_SECRET
        sync: false
```

- [ ] **Step 2: Write `README.md`**

```markdown
# PR Describe Bot

A GitHub App that comments on a pull request when it's missing a description,
and removes the comment once one is added. Built to demonstrate GitHub App
auth (JWT + installation tokens), webhook signature verification, and
idempotent reconciliation against an external API -- no database needed.

## How it works

1. GitHub delivers a `pull_request` webhook (`opened`/`edited`/`synchronize`/`reopened`) to `POST /webhook`.
2. The signature is verified (HMAC-SHA256) against the App's webhook secret.
3. The bot authenticates as the GitHub App (short-lived JWT -> installation access token) and checks the PR body.
4. If the description is missing, it posts (or updates) a single marker-tagged comment on the PR. Once a real description is added, that comment is removed.

## Local development

    python -m pip install -e ".[dev]"
    pytest tests/unit tests/integration -v
    make run

## Creating the GitHub App

1. GitHub -> Settings -> Developer settings -> GitHub Apps -> New GitHub App.
2. Webhook URL: your deployed `/webhook` URL. Generate and save a webhook secret.
3. Permissions: Pull requests (Read & write), Metadata (Read-only).
4. Subscribe to events: Pull request.
5. Generate a private key (downloads a `.pem` file) -- paste its full contents into `GITHUB_APP_PRIVATE_KEY`.
6. Note the App ID (top of the app's settings page) -- goes into `GITHUB_APP_ID`.

## Deploy (Render)

1. Render dashboard -> New -> Blueprint -> point at this repo (reads `render.yaml`).
2. Fill in `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET`.
3. Once deployed, set the GitHub App's webhook URL to `https://<your-service>.onrender.com/webhook`.
4. Install the App on this repository (and any other) to see it in action on real PRs.
```

- [ ] **Step 3: Commit**

```bash
git add render.yaml README.md
git commit -m "docs: deployment config and README"
```

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-08-23-pr-describe-bot-implementation.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - execute tasks in this session, batch execution with checkpoints

**Which approach?**
