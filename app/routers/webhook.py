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
