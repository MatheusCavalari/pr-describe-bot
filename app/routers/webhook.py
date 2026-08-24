import json
import logging

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.clients.github_client import GitHubClient
from app.core.config import settings
from app.core.github_auth import create_app_jwt, get_installation_token
from app.core.locks import get_lock
from app.core.signature import verify_signature
from app.services.description_check import is_description_missing
from app.services.large_pr_check import is_pr_too_large
from app.services.reconcile import (
    DESCRIPTION_CHECK_NAME,
    LARGE_PR_CHECK_NAME,
    build_description_output,
    build_large_pr_output,
    conclusion_for,
    decide_action,
    find_check_run,
)

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
    x_github_delivery: str | None = Header(default=None),
) -> dict[str, object]:
    if not settings.github_webhook_secret:
        logger.error("GITHUB_WEBHOOK_SECRET is not configured; refusing webhook")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="not configured")

    raw_body = await request.body()
    if not verify_signature(raw_body, x_hub_signature_256, settings.github_webhook_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid signature")

    if x_github_event != "pull_request":
        return {"status": "ignored"}

    action = None
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise TypeError("payload is not a JSON object")
        action = payload.get("action")
        if action not in HANDLED_ACTIONS:
            return {"status": "ignored"}

        installation_id = payload["installation"]["id"]
        pr_number = payload["pull_request"]["number"]
        pr_body = payload["pull_request"]["body"]
        additions = payload["pull_request"]["additions"]
        deletions = payload["pull_request"]["deletions"]
        head_sha = payload["pull_request"]["head"]["sha"]
        repo_full_name = payload["repository"]["full_name"]
    except (KeyError, TypeError, AttributeError, json.JSONDecodeError):
        logger.warning(
            "Unexpected payload shape action=%s delivery=%s", action, x_github_delivery
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unexpected payload shape")

    total_changed_lines = additions + deletions

    lock = get_lock(repo_full_name, pr_number)
    async with lock:
        try:
            github_client = await get_github_client(installation_id)

            description_violation = is_description_missing(pr_body)
            large_pr_violation = is_pr_too_large(additions, deletions)
            checks = (
                (DESCRIPTION_CHECK_NAME, description_violation, *build_description_output(description_violation)),
                (
                    LARGE_PR_CHECK_NAME,
                    large_pr_violation,
                    *build_large_pr_output(large_pr_violation, total_changed_lines),
                ),
            )

            actions: dict[str, str] = {}
            debug: dict[str, object] = {}
            for name, violation, title, summary in checks:
                existing_runs = await github_client.list_check_runs_for_ref(
                    repo_full_name, head_sha, name
                )
                debug[f"{name}:existing_runs"] = [{"id": r.id, "name": r.name} for r in existing_runs]
                existing = find_check_run(existing_runs, name)
                result = decide_action(existing)
                conclusion = conclusion_for(violation)

                if result.action == "create":
                    debug[f"{name}:create"] = await github_client.create_check_run(
                        repo_full_name, name, head_sha, conclusion, title, summary
                    )
                else:
                    await github_client.update_check_run(
                        repo_full_name, result.check_run_id, conclusion, title, summary
                    )
                actions[name] = result.action
        except Exception:
            logger.exception(
                "Failed to reconcile check runs for %s#%s", repo_full_name, pr_number
            )
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="reconcile failed")

    return {"status": "ok", "actions": actions, "debug": debug}
