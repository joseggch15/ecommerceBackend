"""Lógica de negocio del módulo de carrito.

- Usuarios registrados: carrito persistente en la base de datos.
- Invitados: carrito temporal en Redis (hash `guest_cart:{token}` con TTL).
- Al iniciar sesión se fusiona el carrito de invitado con el del usuario.
"""

import uuid
from decimal import ROUND_HALF_UP, Decimal

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.modules.cart.models import Cart, CartItem
from app.modules.cart.repository import CartItemRepository, CartRepository
from app.modules.cart.schemas import CartItemOut, CartOut
from app.modules.catalog.models import Product, ProductVariant

GUEST_CART_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 días
MAX_QUANTITY = 100


class CartService:
    """Operaciones del carrito, para usuarios y para invitados."""

    def __init__(self, session: AsyncSession, redis: Redis) -> None:
        self._session = session
        self._redis = redis
        self._carts = CartRepository(session)
        self._items = CartItemRepository(session)

    async def get_cart(self, *, user_id: uuid.UUID | None, guest_token: str | None) -> CartOut:
        if user_id is not None:
            cart = await self._carts.get_by_user(user_id)
            if cart is None:
                return self._build([])
            return self._build(await self._user_entries(cart.id))

        quantities = await self._guest_items(guest_token)
        return self._build(await self._guest_entries(quantities))

    async def add_item(
        self,
        *,
        user_id: uuid.UUID | None,
        guest_token: str | None,
        variant_id: uuid.UUID,
        quantity: int,
    ) -> CartOut:
        if await self._load_variant(variant_id) is None:
            raise AppError(404, "variant_not_found", "Variant not found.")

        if user_id is not None:
            cart = await self._ensure_cart(user_id)
            existing = await self._items.get(cart.id, variant_id)
            new_quantity = quantity + (existing.quantity if existing is not None else 0)
            self._validate_quantity(new_quantity)

            if existing is None:
                await self._items.add(
                    CartItem(cart_id=cart.id, variant_id=variant_id, quantity=new_quantity)
                )
            else:
                existing.quantity = new_quantity
            await self._session.commit()
            return await self.get_cart(user_id=user_id, guest_token=None)

        token = self._require_token(guest_token)
        key = self._guest_key(token)
        current = await self._guest_quantity(key, variant_id)
        new_guest_quantity = current + quantity
        self._validate_quantity(new_guest_quantity)
        await self._redis.hset(key, str(variant_id), new_guest_quantity)
        await self._redis.expire(key, GUEST_CART_TTL_SECONDS)
        return await self.get_cart(user_id=None, guest_token=token)

    async def update_item(
        self,
        *,
        user_id: uuid.UUID | None,
        guest_token: str | None,
        variant_id: uuid.UUID,
        quantity: int,
    ) -> CartOut:
        self._validate_quantity(quantity)

        if user_id is not None:
            cart = await self._carts.get_by_user(user_id)
            if cart is None:
                raise AppError(404, "cart_item_not_found", "Item not found in cart.")
            item = await self._items.get(cart.id, variant_id)
            if item is None:
                raise AppError(404, "cart_item_not_found", "Item not found in cart.")
            item.quantity = quantity
            await self._session.commit()
            return await self.get_cart(user_id=user_id, guest_token=None)

        token = self._require_token(guest_token)
        quantities = await self._guest_items(token)
        if str(variant_id) not in quantities:
            raise AppError(404, "cart_item_not_found", "Item not found in cart.")
        await self._redis.hset(self._guest_key(token), str(variant_id), quantity)
        await self._redis.expire(self._guest_key(token), GUEST_CART_TTL_SECONDS)
        return await self.get_cart(user_id=None, guest_token=token)

    async def remove_item(
        self, *, user_id: uuid.UUID | None, guest_token: str | None, variant_id: uuid.UUID
    ) -> CartOut:
        if user_id is not None:
            cart = await self._carts.get_by_user(user_id)
            if cart is not None:
                item = await self._items.get(cart.id, variant_id)
                if item is not None:
                    await self._items.delete(item)
                    await self._session.commit()
            return await self.get_cart(user_id=user_id, guest_token=None)

        token = self._require_token(guest_token)
        await self._redis.hdel(self._guest_key(token), str(variant_id))
        return await self.get_cart(user_id=None, guest_token=token)

    async def clear(self, *, user_id: uuid.UUID | None, guest_token: str | None) -> CartOut:
        if user_id is not None:
            cart = await self._carts.get_by_user(user_id)
            if cart is not None:
                await self._items.delete_all(cart.id)
                await self._session.commit()
            return await self.get_cart(user_id=user_id, guest_token=None)

        if guest_token:
            await self._redis.delete(self._guest_key(guest_token))
        return self._build([])

    async def merge(self, *, user_id: uuid.UUID, guest_token: str | None) -> CartOut:
        """Fusiona el carrito de invitado con el del usuario (al iniciar sesión)."""
        quantities = await self._guest_items(guest_token)
        if quantities:
            cart = await self._ensure_cart(user_id)
            for variant_id_str, quantity in quantities.items():
                try:
                    variant_id = uuid.UUID(variant_id_str)
                except ValueError:
                    continue
                existing = await self._items.get(cart.id, variant_id)
                new_quantity = min(
                    quantity + (existing.quantity if existing is not None else 0), MAX_QUANTITY
                )
                if existing is None:
                    await self._items.add(
                        CartItem(cart_id=cart.id, variant_id=variant_id, quantity=new_quantity)
                    )
                else:
                    existing.quantity = new_quantity
            await self._session.commit()
            if guest_token:
                await self._redis.delete(self._guest_key(guest_token))
        return await self.get_cart(user_id=user_id, guest_token=None)

    # ---------- Internos ----------

    async def _ensure_cart(self, user_id: uuid.UUID) -> Cart:
        cart = await self._carts.get_by_user(user_id)
        if cart is None:
            cart = await self._carts.add(Cart(user_id=user_id))
        return cart

    async def _user_entries(self, cart_id: uuid.UUID) -> list[tuple[ProductVariant, Product, int]]:
        result = await self._session.execute(
            select(ProductVariant, Product, CartItem.quantity)
            .join(CartItem, CartItem.variant_id == ProductVariant.id)
            .join(Product, ProductVariant.product_id == Product.id)
            .where(CartItem.cart_id == cart_id)
            .order_by(CartItem.created_at)
        )
        return list(result.tuples().all())

    async def _guest_entries(
        self, quantities: dict[str, int]
    ) -> list[tuple[ProductVariant, Product, int]]:
        if not quantities:
            return []
        variant_ids = [uuid.UUID(value) for value in quantities]
        result = await self._session.execute(
            select(ProductVariant, Product)
            .join(Product, ProductVariant.product_id == Product.id)
            .where(ProductVariant.id.in_(variant_ids))
        )
        return [
            (variant, product, quantities[str(variant.id)])
            for variant, product in result.tuples().all()
        ]

    async def _load_variant(self, variant_id: uuid.UUID) -> ProductVariant | None:
        result = await self._session.execute(
            select(ProductVariant).where(ProductVariant.id == variant_id)
        )
        return result.scalar_one_or_none()

    def _build(self, entries: list[tuple[ProductVariant, Product, int]]) -> CartOut:
        items: list[CartItemOut] = []
        subtotal = Decimal("0")
        total_items = 0

        for variant, product, quantity in entries:
            line_total = (variant.price * quantity).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            subtotal += line_total
            total_items += quantity
            items.append(
                CartItemOut(
                    variant_id=variant.id,
                    sku=variant.sku,
                    product_id=product.id,
                    product_title=product.title,
                    product_slug=product.slug,
                    store_id=product.store_id,
                    unit_price=variant.price,
                    quantity=quantity,
                    subtotal=line_total,
                )
            )

        return CartOut(
            items=items,
            total_items=total_items,
            subtotal=subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            currency=settings.DEFAULT_CURRENCY,
        )

    async def _guest_items(self, token: str | None) -> dict[str, int]:
        if not token:
            return {}
        data = await self._redis.hgetall(self._guest_key(token))
        return {str(field): int(value) for field, value in data.items()}

    async def _guest_quantity(self, key: str, variant_id: uuid.UUID) -> int:
        value = await self._redis.hget(key, str(variant_id))
        return int(value) if value is not None else 0

    @staticmethod
    def _guest_key(token: str) -> str:
        return f"guest_cart:{token}"

    @staticmethod
    def _require_token(guest_token: str | None) -> str:
        if not guest_token:
            raise AppError(
                status_code=400,
                code="cart_token_required",
                detail="A cart token (X-Cart-Token) is required for guests.",
            )
        return guest_token

    @staticmethod
    def _validate_quantity(quantity: int) -> None:
        if quantity > MAX_QUANTITY:
            raise AppError(
                status_code=400,
                code="quantity_limit_exceeded",
                detail=f"Maximum quantity per item is {MAX_QUANTITY}.",
            )
