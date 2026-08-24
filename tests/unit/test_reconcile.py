from app.clients.github_client import Comment
from app.services.reconcile import (
    DESCRIPTION_MARKER,
    DESCRIPTION_NAG_MESSAGE,
    LARGE_PR_MARKER,
    Action,
    build_large_pr_message,
    decide_action,
    find_marker_comment,
)


def test_nag_message_contains_the_marker():
    assert DESCRIPTION_MARKER in DESCRIPTION_NAG_MESSAGE


def test_large_pr_message_contains_the_marker():
    assert LARGE_PR_MARKER in build_large_pr_message(600)


def test_large_pr_message_mentions_the_line_count():
    assert "600" in build_large_pr_message(600)


def test_find_marker_comment_returns_none_when_absent():
    comments = [
        Comment(id=1, body="just chatting", is_bot=True),
        Comment(id=2, body="+1", is_bot=True),
    ]
    assert find_marker_comment(comments, DESCRIPTION_MARKER) is None


def test_find_marker_comment_finds_the_one_with_the_marker():
    target = Comment(id=2, body=f"please add a description\n{DESCRIPTION_MARKER}", is_bot=True)
    comments = [Comment(id=1, body="unrelated", is_bot=True), target]
    assert find_marker_comment(comments, DESCRIPTION_MARKER) is target


def test_find_marker_comment_ignores_a_human_comment_that_quotes_the_marker():
    # A human quoting/replying to the bot's comment preserves the HTML
    # comment marker in their own comment body -- it must not be mistaken
    # for the bot's own comment (which would risk editing/deleting it).
    human_quote = Comment(id=3, body=f"> {DESCRIPTION_MARKER}\nI'll add one!", is_bot=False)
    assert find_marker_comment([human_quote], DESCRIPTION_MARKER) is None


def test_find_marker_comment_distinguishes_between_different_markers():
    description_comment = Comment(id=1, body=f"text\n{DESCRIPTION_MARKER}", is_bot=True)
    large_pr_comment = Comment(id=2, body=f"text\n{LARGE_PR_MARKER}", is_bot=True)
    comments = [description_comment, large_pr_comment]
    assert find_marker_comment(comments, DESCRIPTION_MARKER) is description_comment
    assert find_marker_comment(comments, LARGE_PR_MARKER) is large_pr_comment


def test_violation_and_no_existing_comment_creates():
    result = decide_action(violation=True, existing_comment=None)
    assert result.action == Action.CREATE
    assert result.comment_id is None


def test_violation_and_existing_comment_updates():
    existing = Comment(id=7, body=f"old message\n{DESCRIPTION_MARKER}", is_bot=True)
    result = decide_action(violation=True, existing_comment=existing)
    assert result.action == Action.UPDATE
    assert result.comment_id == 7


def test_no_violation_and_existing_comment_deletes():
    existing = Comment(id=7, body=f"old message\n{DESCRIPTION_MARKER}", is_bot=True)
    result = decide_action(violation=False, existing_comment=existing)
    assert result.action == Action.DELETE
    assert result.comment_id == 7


def test_no_violation_and_no_existing_comment_is_noop():
    result = decide_action(violation=False, existing_comment=None)
    assert result.action == Action.NOOP
    assert result.comment_id is None
