"""Utilidades de seguridad: hashing de contraseñas (Argon2id) y tokens JWT."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash

from app.core.config import settings

# Argon2id: algoritmo recomendado para hashear contraseñas.
password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """Devuelve el hash Argon2id de una contraseña en texto plano."""
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verifica una contraseña en texto plano contra su hash."""
    return password_hasher.verify(password, password_hash)


def create_access_token(user_id: str) -> str:
    """Crea un access token JWT de corta duración."""
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": user_id,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decodifica y valida un access token; lanza PyJWTError si es inválido."""
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


def generate_opaque_token() -> str:
    """Genera un token opaco aleatorio (para refresh, verificación, etc.)."""
    return secrets.token_urlsafe(64)


def hash_token(token: str) -> str:
    """Devuelve el hash SHA-256 (hex) de un token opaco para guardarlo en BD."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
