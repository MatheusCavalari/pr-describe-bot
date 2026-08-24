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
    DESCRIPTION_MARKER,
    DESCRIPTION_NAG_MESSAGE,
    LARGE_PR_MARKER,
    Action,
    build_large_pr_message,
    decide_action,
    find_marker_comment,
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
        repo_full_name = payload["repository"]["full_name"]
    except (KeyError, TypeError, AttributeError, json.JSONDecodeError):
        logger.warning(
            "Unexpected payload shape action=%s delivery=%s", action, x_github_delivery
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unexpected payload shape")

    lock = get_lock(repo_full_name, pr_number)
    async with lock:
        try:
            github_client = await get_github_client(installation_id)
            comments = await github_client.list_issue_comments(repo_full_name, pr_number)

            checks = (
                ("description", DESCRIPTION_MARKER, is_description_missing(pr_body), DESCRIPTION_NAG_MESSAGE),
                (
                    "large_pr",
                    LARGE_PR_MARKER,
                    is_pr_too_large(additions, deletions),
                    build_large_pr_message(additions + deletions),
                ),
            )

            actions: dict[str, str] = {}
            for name, marker, violation, message in checks:
                existing = find_marker_comment(comments, marker)
                result = decide_action(violation, existing)

                if result.action == Action.CREATE:
                    await github_client.create_comment(repo_full_name, pr_number, message)
                elif result.action == Action.UPDATE:
                    await github_client.update_comment(repo_full_name, result.comment_id, message)
                elif result.action == Action.DELETE:
                    await github_client.delete_comment(repo_full_name, result.comment_id)
                actions[name] = result.action.value
        except Exception:
            logger.exception(
                "Failed to reconcile PR comments for %s#%s", repo_full_name, pr_number
            )
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="reconcile failed")

    return {"status": "ok", "actions": actions}
