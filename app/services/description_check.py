import re

MIN_DESCRIPTION_LENGTH = 20
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def is_description_missing(body: str | None) -> bool:
    if body is None:
        return True
    stripped = _HTML_COMMENT_RE.sub("", body).strip()
    return len(stripped) < MIN_DESCRIPTION_LENGTH
