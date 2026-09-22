"""Endpoints del módulo de carrito.

El carrito del usuario registrado es persistente; el del invitado es temporal
(Redis) y se identifica con el header `X-Cart-Token`. Si el invitado no lo
envía, la API genera uno y lo devuelve en el mismo header de la respuesta.
"""

import uuid
from dataclasses import dataclass

from fastapi import APIRouter, Depends, Header, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.redis import get_redis
from app.modules.cart.schemas import CartItemAdd, CartItemUpdate, CartOut
from app.modules.cart.service import CartService
from app.modules.identity.deps import get_current_user, get_optional_user
from app.modules.identity.models import User

router = APIRouter(prefix="/cart", tags=["cart"])

CART_TOKEN_HEADER = "X-Cart-Token"


@dataclass(frozen=True)
class CartIdentity:
    """Identidad del carrito: usuario registrado o invitado (token)."""

    user_id: uuid.UUID | None
    guest_token: str | None
    token_generated: bool = False


def get_cart_service(
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> CartService:
    return CartService(session, redis)


def get_cart_identity(
    user: User | None = Depends(get_optional_user),
    x_cart_token: str | None = Header(default=None, alias=CART_TOKEN_HEADER),
) -> CartIdentity:
    """Resuelve de quién es el carrito: del usuario o de un invitado."""
    if user is not None:
        return CartIdentity(user_id=user.id, guest_token=x_cart_token)
    if x_cart_token:
        return CartIdentity(user_id=None, guest_token=x_cart_token)
    return CartIdentity(user_id=None, guest_token=uuid.uuid4().hex, token_generated=True)


def _expose_token(response: Response, identity: CartIdentity) -> None:
    """Devuelve el token recién generado para que el cliente lo conserve."""
    if identity.token_generated and identity.guest_token:
        response.headers[CART_TOKEN_HEADER] = identity.guest_token


@router.get("", response_model=CartOut)
async def get_cart(
    response: Response,
    identity: CartIdentity = Depends(get_cart_identity),
    service: CartService = Depends(get_cart_service),
) -> CartOut:
    """Devuelve el carrito actual (del usuario o del invitado)."""
    _expose_token(response, identity)
    return await service.get_cart(user_id=identity.user_id, guest_token=identity.guest_token)


@router.post("/items", response_model=CartOut)
async def add_item(
    data: CartItemAdd,
    response: Response,
    identity: CartIdentity = Depends(get_cart_identity),
    service: CartService = Depends(get_cart_service),
) -> CartOut:
    """Añade (o incrementa) una variante en el carrito."""
    _expose_token(response, identity)
    return await service.add_item(
        user_id=identity.user_id,
        guest_token=identity.guest_token,
        variant_id=data.variant_id,
        quantity=data.quantity,
    )


@router.patch("/items/{variant_id}", response_model=CartOut)
async def update_item(
    variant_id: uuid.UUID,
    data: CartItemUpdate,
    response: Response,
    identity: CartIdentity = Depends(get_cart_identity),
    service: CartService = Depends(get_cart_service),
) -> CartOut:
    """Cambia la cantidad de una variante del carrito."""
    _expose_token(response, identity)
    return await service.update_item(
        user_id=identity.user_id,
        guest_token=identity.guest_token,
        variant_id=variant_id,
        quantity=data.quantity,
    )


@router.delete("/items/{variant_id}", response_model=CartOut)
async def remove_item(
    variant_id: uuid.UUID,
    response: Response,
    identity: CartIdentity = Depends(get_cart_identity),
    service: CartService = Depends(get_cart_service),
) -> CartOut:
    """Quita una variante del carrito."""
    _expose_token(response, identity)
    return await service.remove_item(
        user_id=identity.user_id, guest_token=identity.guest_token, variant_id=variant_id
    )


@router.delete("", response_model=CartOut)
async def clear_cart(
    response: Response,
    identity: CartIdentity = Depends(get_cart_identity),
    service: CartService = Depends(get_cart_service),
) -> CartOut:
    """Vacía el carrito."""
    _expose_token(response, identity)
    return await service.clear(user_id=identity.user_id, guest_token=identity.guest_token)


@router.post("/merge", response_model=CartOut)
async def merge_cart(
    response: Response,
    user: User = Depends(get_current_user),
    x_cart_token: str | None = Header(default=None, alias=CART_TOKEN_HEADER),
    service: CartService = Depends(get_cart_service),
) -> CartOut:
    """Fusiona el carrito de invitado con el del usuario (llamar tras iniciar sesión)."""
    response.headers[CART_TOKEN_HEADER] = ""
    return await service.merge(user_id=user.id, guest_token=x_cart_token)
