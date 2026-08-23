import hashlib
import hmac

from app.core.signature import verify_signature

SECRET = "test-secret"
BODY = b'{"action": "opened"}'


def _sign(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_accepts_a_valid_signature():
    assert verify_signature(BODY, _sign(BODY, SECRET), SECRET) is True


def test_rejects_a_signature_signed_with_the_wrong_secret():
    assert verify_signature(BODY, _sign(BODY, "wrong-secret"), SECRET) is False


def test_rejects_a_signature_for_a_different_body():
    wrong_body_signature = _sign(b'{"action": "closed"}', SECRET)
    assert verify_signature(BODY, wrong_body_signature, SECRET) is False


def test_rejects_a_missing_header():
    assert verify_signature(BODY, None, SECRET) is False


def test_rejects_a_header_without_the_sha256_prefix():
    digest = hmac.new(SECRET.encode("utf-8"), BODY, hashlib.sha256).hexdigest()
    assert verify_signature(BODY, digest, SECRET) is False
