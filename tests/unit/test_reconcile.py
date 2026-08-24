from app.clients.github_client import CheckRun
from app.services.reconcile import (
    DESCRIPTION_CHECK_NAME,
    LARGE_PR_CHECK_NAME,
    build_description_output,
    build_large_pr_output,
    conclusion_for,
    decide_action,
    find_check_run,
)


def test_description_output_when_missing():
    title, summary = build_description_output(violation=True)
    assert title == "Description missing"
    assert "description" in summary.lower()


def test_description_output_when_present():
    title, _summary = build_description_output(violation=False)
    assert title == "Description present"


def test_large_pr_output_when_too_large_mentions_the_line_count():
    title, summary = build_large_pr_output(violation=True, total_changed_lines=600)
    assert "600" in title
    assert "600" in summary


def test_large_pr_output_when_reasonable_size():
    title, _summary = build_large_pr_output(violation=False, total_changed_lines=50)
    assert "50" in title


def test_conclusion_is_failure_for_a_violation():
    assert conclusion_for(violation=True) == "failure"


def test_conclusion_is_success_without_a_violation():
    assert conclusion_for(violation=False) == "success"


def test_find_check_run_returns_none_when_absent():
    runs = [CheckRun(id=1, name="some-other-check")]
    assert find_check_run(runs, DESCRIPTION_CHECK_NAME) is None


def test_find_check_run_finds_by_name():
    target = CheckRun(id=2, name=LARGE_PR_CHECK_NAME)
    runs = [CheckRun(id=1, name=DESCRIPTION_CHECK_NAME), target]
    assert find_check_run(runs, LARGE_PR_CHECK_NAME) is target


def test_decide_action_creates_when_no_existing_run():
    result = decide_action(existing_run=None)
    assert result.action == "create"
    assert result.check_run_id is None


def test_decide_action_updates_when_a_run_already_exists():
    existing = CheckRun(id=9, name=DESCRIPTION_CHECK_NAME)
    result = decide_action(existing_run=existing)
    assert result.action == "update"
    assert result.check_run_id == 9
