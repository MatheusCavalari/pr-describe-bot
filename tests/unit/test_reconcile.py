from app.clients.github_client import Comment
from app.services.reconcile import (
    MARKER,
    NAG_MESSAGE,
    Action,
    decide_action,
    find_marker_comment,
)


def test_nag_message_contains_the_marker():
    assert MARKER in NAG_MESSAGE


def test_find_marker_comment_returns_none_when_absent():
    comments = [Comment(id=1, body="just chatting"), Comment(id=2, body="+1")]
    assert find_marker_comment(comments) is None


def test_find_marker_comment_finds_the_one_with_the_marker():
    target = Comment(id=2, body=f"please add a description\n{MARKER}")
    comments = [Comment(id=1, body="unrelated"), target]
    assert find_marker_comment(comments) is target


def test_missing_description_and_no_existing_comment_creates():
    result = decide_action(description_missing=True, existing_comment=None)
    assert result.action == Action.CREATE
    assert result.comment_id is None


def test_missing_description_and_existing_comment_updates():
    existing = Comment(id=7, body=f"old message\n{MARKER}")
    result = decide_action(description_missing=True, existing_comment=existing)
    assert result.action == Action.UPDATE
    assert result.comment_id == 7


def test_description_present_and_existing_comment_deletes():
    existing = Comment(id=7, body=f"old message\n{MARKER}")
    result = decide_action(description_missing=False, existing_comment=existing)
    assert result.action == Action.DELETE
    assert result.comment_id == 7


def test_description_present_and_no_existing_comment_is_noop():
    result = decide_action(description_missing=False, existing_comment=None)
    assert result.action == Action.NOOP
    assert result.comment_id is None
