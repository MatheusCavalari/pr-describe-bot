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
