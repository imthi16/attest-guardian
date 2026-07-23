"""Access-token and refresh-token primitive behavior."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt as pyjwt
import pytest
from app.auth import tokens

SECRET = "unit-test-secret"


def test_access_token_roundtrip() -> None:
    user_id = uuid.uuid4()
    token = tokens.issue_access_token(user_id, secret=SECRET, ttl_seconds=60)
    assert tokens.decode_access_token(token, secret=SECRET) == user_id


def test_expired_access_token_is_rejected() -> None:
    token = tokens.issue_access_token(
        uuid.uuid4(),
        secret=SECRET,
        ttl_seconds=30,
        now=datetime.now(UTC) - timedelta(minutes=5),
    )
    with pytest.raises(tokens.InvalidTokenError):
        tokens.decode_access_token(token, secret=SECRET)


def test_wrong_secret_is_rejected() -> None:
    token = tokens.issue_access_token(uuid.uuid4(), secret=SECRET, ttl_seconds=60)
    with pytest.raises(tokens.InvalidTokenError):
        tokens.decode_access_token(token, secret="a-different-secret")


def test_garbage_token_is_rejected() -> None:
    with pytest.raises(tokens.InvalidTokenError):
        tokens.decode_access_token("not-a-jwt", secret=SECRET)


def test_wrong_token_type_claim_is_rejected() -> None:
    now = datetime.now(UTC)
    forged = pyjwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "typ": "refresh",
            "iat": now,
            "exp": now + timedelta(seconds=60),
        },
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(tokens.InvalidTokenError):
        tokens.decode_access_token(forged, secret=SECRET)


def test_non_uuid_subject_is_rejected() -> None:
    now = datetime.now(UTC)
    forged = pyjwt.encode(
        {"sub": "root", "typ": "access", "iat": now, "exp": now + timedelta(seconds=60)},
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(tokens.InvalidTokenError):
        tokens.decode_access_token(forged, secret=SECRET)


def test_refresh_tokens_are_unique_and_hash_is_stable() -> None:
    first = tokens.generate_refresh_token()
    second = tokens.generate_refresh_token()
    assert first != second
    digest = tokens.hash_refresh_token(first)
    assert digest == tokens.hash_refresh_token(first)
    assert len(digest) == 64
    assert digest != first
