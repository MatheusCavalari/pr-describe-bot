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
