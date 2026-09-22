"""CLI para ascender un usuario a administrador (uso en desarrollo).

Uso:
    uv run python -m app.scripts.promote_admin correo@ejemplo.com
"""

import asyncio
import sys

from sqlalchemy import select

from app.core.database import async_session_factory
from app.modules.identity.models import User, UserRole


async def promote(email: str) -> None:
    """Establece el rol admin al usuario indicado por email."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(User.email == email, User.deleted_at.is_(None))
        )
        user = result.scalar_one_or_none()
        if user is None:
            print(f"No se encontró el usuario '{email}'.")
            return
        user.role = UserRole.ADMIN
        await session.commit()
        print(f"El usuario '{email}' ahora es administrador.")


def main() -> None:
    if len(sys.argv) != 2:
        print("Uso: uv run python -m app.scripts.promote_admin <email>")
        sys.exit(1)
    asyncio.run(promote(sys.argv[1]))


if __name__ == "__main__":
    main()
