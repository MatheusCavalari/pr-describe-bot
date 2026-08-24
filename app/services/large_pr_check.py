LARGE_PR_THRESHOLD = 500


def is_pr_too_large(additions: int, deletions: int) -> bool:
    return (additions + deletions) > LARGE_PR_THRESHOLD
