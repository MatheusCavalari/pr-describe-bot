from dataclasses import dataclass

from app.clients.github_client import CheckRun
from app.services.large_pr_check import LARGE_PR_THRESHOLD

DESCRIPTION_CHECK_NAME = "pr-describe-bot/description"
LARGE_PR_CHECK_NAME = "pr-describe-bot/pr-size"


def build_description_output(violation: bool) -> tuple[str, str]:
    if violation:
        return (
            "Description missing",
            (
                "This PR doesn't have a description yet. Mind adding one? It helps reviewers "
                "(and future you) understand the *why* behind the change."
            ),
        )
    return ("Description present", "This PR has a description. 👍")


def build_large_pr_output(violation: bool, total_changed_lines: int) -> tuple[str, str]:
    if violation:
        return (
            f"{total_changed_lines} lines changed",
            (
                f"This PR changes {total_changed_lines} lines (additions + deletions), over the "
                f"{LARGE_PR_THRESHOLD}-line guideline. Consider splitting it into smaller PRs — "
                "they get reviewed faster and more thoroughly."
            ),
        )
    return (f"{total_changed_lines} lines changed", "This PR is a reasonable size. 👍")


def conclusion_for(violation: bool) -> str:
    return "failure" if violation else "success"


@dataclass
class ReconcileResult:
    action: str  # "create" | "update"
    check_run_id: int | None = None


def find_check_run(check_runs: list[CheckRun], name: str) -> CheckRun | None:
    for run in check_runs:
        if run.name == name:
            return run
    return None


def decide_action(existing_run: CheckRun | None) -> ReconcileResult:
    if existing_run is None:
        return ReconcileResult("create")
    return ReconcileResult("update", existing_run.id)
