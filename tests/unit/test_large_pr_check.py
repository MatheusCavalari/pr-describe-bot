from app.services.large_pr_check import LARGE_PR_THRESHOLD, is_pr_too_large


def test_small_pr_is_not_too_large():
    assert is_pr_too_large(additions=10, deletions=5) is False


def test_pr_right_at_the_threshold_is_not_too_large():
    assert is_pr_too_large(additions=LARGE_PR_THRESHOLD, deletions=0) is False


def test_pr_one_line_over_the_threshold_is_too_large():
    assert is_pr_too_large(additions=LARGE_PR_THRESHOLD + 1, deletions=0) is True


def test_additions_and_deletions_are_summed():
    assert is_pr_too_large(additions=300, deletions=300) is True
