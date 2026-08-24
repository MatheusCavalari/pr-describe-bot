from dataclasses import dataclass
from enum import Enum

from app.clients.github_client import Comment
from app.services.large_pr_check import LARGE_PR_THRESHOLD

DESCRIPTION_MARKER = "<!-- pr-describe-bot:description-marker -->"

DESCRIPTION_NAG_MESSAGE = (
    "👋 This PR doesn't have a description yet. Mind adding one? "
    "It helps reviewers (and future you) understand the *why* behind the change.\n\n"
    + DESCRIPTION_MARKER
)

LARGE_PR_MARKER = "<!-- pr-describe-bot:large-pr-marker -->"


def build_large_pr_message(total_changed_lines: int) -> str:
    return (
        f"📏 This PR changes {total_changed_lines} lines (additions + deletions), "
        f"over the {LARGE_PR_THRESHOLD}-line guideline. Consider splitting it into "
        "smaller PRs — they get reviewed faster and more thoroughly.\n\n" + LARGE_PR_MARKER
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


def find_marker_comment(comments: list[Comment], marker: str) -> Comment | None:
    # Only a comment actually authored by a bot can be "ours" -- a human
    # quoting/replying-with-quote to the bot's comment would otherwise match
    # on the marker text and risk having their own comment edited or deleted.
    for comment in comments:
        if comment.is_bot and marker in comment.body:
            return comment
    return None


def decide_action(violation: bool, existing_comment: Comment | None) -> ReconcileResult:
    if violation:
        if existing_comment is None:
            return ReconcileResult(Action.CREATE)
        return ReconcileResult(Action.UPDATE, existing_comment.id)
    if existing_comment is not None:
        return ReconcileResult(Action.DELETE, existing_comment.id)
    return ReconcileResult(Action.NOOP)
