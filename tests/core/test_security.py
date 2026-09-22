"""Pruebas unitarias de las utilidades de seguridad."""

from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_opaque_token,
    hash_password,
    hash_token,
    verify_password,
)


def test_hash_and_verify_password() -> None:
    hashed = hash_password("super-secret-123")
    assert hashed != "super-secret-123"
    assert verify_password("super-secret-123", hashed) is True
    assert verify_password("wrong-password", hashed) is False


def test_access_token_roundtrip() -> None:
    user_id = "00000000-0000-0000-0000-000000000000"
    payload = decode_access_token(create_access_token(user_id))
    assert payload["sub"] == user_id
    assert payload["type"] == "access"


def test_opaque_token_is_hashed_consistently() -> None:
    token = generate_opaque_token()
    assert len(token) > 40
    assert hash_token(token) == hash_token(token)
    assert hash_token(token) != hash_token(generate_opaque_token())
