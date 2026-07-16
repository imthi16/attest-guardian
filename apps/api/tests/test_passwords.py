"""Password hashing behavior."""

from app.auth import passwords


def test_hash_and_verify_roundtrip() -> None:
    encoded = passwords.hash_password("correct horse battery staple")
    assert encoded != "correct horse battery staple"
    assert encoded.startswith("$argon2id$")
    assert passwords.verify_password(encoded, "correct horse battery staple")


def test_verify_rejects_wrong_password() -> None:
    encoded = passwords.hash_password("correct horse battery staple")
    assert not passwords.verify_password(encoded, "incorrect horse")


def test_verify_rejects_garbage_hash_without_raising() -> None:
    assert not passwords.verify_password("not-a-hash", "anything")


def test_hashes_are_salted() -> None:
    assert passwords.hash_password("same input") != passwords.hash_password("same input")


def test_burn_verification_time_never_raises() -> None:
    passwords.burn_verification_time("any candidate")
