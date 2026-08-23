from app.services.description_check import is_description_missing


def test_none_body_is_missing():
    assert is_description_missing(None) is True


def test_empty_string_is_missing():
    assert is_description_missing("") is True


def test_whitespace_only_is_missing():
    assert is_description_missing("   \n\t  ") is True


def test_short_text_is_missing():
    assert is_description_missing("fixed it") is True


def test_only_html_comment_is_missing():
    body = "<!-- This is an auto-generated PR template. Please fill me in! -->"
    assert is_description_missing(body) is True


def test_long_enough_real_text_is_not_missing():
    body = "This PR fixes the off-by-one error in the pagination cursor calculation."
    assert is_description_missing(body) is False


def test_html_comment_is_stripped_before_measuring_length():
    body = (
        "<!-- template boilerplate that should not count -->\n"
        "Short."
    )
    assert is_description_missing(body) is True
