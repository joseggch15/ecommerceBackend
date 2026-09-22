"""Lógica de negocio del módulo de carrito.

- Usuarios registrados: carrito persistente en la base de datos.
- Invitados: carrito temporal en Redis (hash `guest_cart:{token}` con TTL).
- Al iniciar sesión se fusiona el carrito de invitado con el del usuario.

Cada línea guarda el **precio de cuando se añadió** (`unit_price_snapshot`; en el carrito de
invitado va dentro del propio valor de Redis). Con eso la respuesta puede avisar de que el precio
cambió y de cuántas unidades quedan disponibles, sin inventarse ningún dato.
"""

import json
import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.modules.cart.models import Cart, CartItem
from app.modules.cart.repository import CartItemRepository, CartRepository
from app.modules.cart.schemas import CartItemOut, CartOut
from app.modules.catalog.models import Product, ProductImage, ProductVariant
from app.modules.catalog.repository import VariantValueRepository
from app.modules.catalog.schemas import VariantValueOut
from app.modules.inventory.service import InventoryService

GUEST_CART_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 días
MAX_QUANTITY = 100


@dataclass(frozen=True)
class CartLine:
    """Línea antes de calcular la respuesta: variante, producto, cantidad y precio de entonces."""

    variant: ProductVariant
    product: Product
    quantity: int
    unit_price_snapshot: Decimal | None


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
                return await self._build([])
            return await self._build(await self._user_entries(cart.id))

        quantities = await self._guest_items(guest_token)
        return await self._build(await self._guest_entries(quantities))

    async def add_item(
        self,
        *,
        user_id: uuid.UUID | None,
        guest_token: str | None,
        variant_id: uuid.UUID,
        quantity: int,
    ) -> CartOut:
        variant = await self._load_variant(variant_id)
        if variant is None:
            raise AppError(404, "variant_not_found", "Variant not found.")

        if user_id is not None:
            cart = await self._ensure_cart(user_id)
            existing = await self._items.get(cart.id, variant_id)
            new_quantity = quantity + (existing.quantity if existing is not None else 0)
            self._validate_quantity(new_quantity)
            await self._check_availability(variant_id, new_quantity)

            if existing is None:
                await self._items.add(
                    CartItem(
                        cart_id=cart.id,
                        variant_id=variant_id,
                        quantity=new_quantity,
                        # Precio del momento de añadir: es lo que permite avisar de un cambio.
                        unit_price_snapshot=variant.price,
                    )
                )
            else:
                existing.quantity = new_quantity
            await self._session.commit()
            return await self.get_cart(user_id=user_id, guest_token=None)

        token = self._require_token(guest_token)
        key = self._guest_key(token)
        current_quantity, current_price = (await self._guest_items(token)).get(
            str(variant_id), (0, None)
        )
        new_guest_quantity = current_quantity + quantity
        self._validate_quantity(new_guest_quantity)
        await self._check_availability(variant_id, new_guest_quantity)
        await self._redis.hset(
            key,
            str(variant_id),
            self._guest_payload(new_guest_quantity, current_price or variant.price),
        )
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
            await self._check_availability(variant_id, quantity)
            item.quantity = quantity
            await self._session.commit()
            return await self.get_cart(user_id=user_id, guest_token=None)

        token = self._require_token(guest_token)
        lines = await self._guest_items(token)
        if str(variant_id) not in lines:
            raise AppError(404, "cart_item_not_found", "Item not found in cart.")
        await self._check_availability(variant_id, quantity)
        await self._redis.hset(
            self._guest_key(token),
            str(variant_id),
            self._guest_payload(quantity, lines[str(variant_id)][1]),
        )
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
        return await self._build([])

    async def merge(self, *, user_id: uuid.UUID, guest_token: str | None) -> CartOut:
        """Fusiona el carrito de invitado con el del usuario (al iniciar sesión)."""
        guest_lines = await self._guest_items(guest_token)
        if guest_lines:
            cart = await self._ensure_cart(user_id)
            for variant_id_str, (quantity, snapshot) in guest_lines.items():
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
                        CartItem(
                            cart_id=cart.id,
                            variant_id=variant_id,
                            quantity=new_quantity,
                            unit_price_snapshot=snapshot,
                        )
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

    async def _user_entries(self, cart_id: uuid.UUID) -> list[CartLine]:
        result = await self._session.execute(
            select(ProductVariant, Product, CartItem.quantity, CartItem.unit_price_snapshot)
            .join(CartItem, CartItem.variant_id == ProductVariant.id)
            .join(Product, ProductVariant.product_id == Product.id)
            .where(CartItem.cart_id == cart_id)
            .order_by(CartItem.created_at)
        )
        return [
            CartLine(
                variant=row[0], product=row[1], quantity=row[2], unit_price_snapshot=row[3]
            )
            for row in result.tuples().all()
        ]

    async def _guest_entries(
        self, quantities: dict[str, tuple[int, Decimal | None]]
    ) -> list[CartLine]:
        if not quantities:
            return []
        variant_ids = [uuid.UUID(value) for value in quantities]
        result = await self._session.execute(
            select(ProductVariant, Product)
            .join(Product, ProductVariant.product_id == Product.id)
            .where(ProductVariant.id.in_(variant_ids))
        )
        lines: list[CartLine] = []
        for variant, product in result.tuples().all():
            quantity, snapshot = quantities[str(variant.id)]
            lines.append(
                CartLine(
                    variant=variant,
                    product=product,
                    quantity=quantity,
                    unit_price_snapshot=snapshot,
                )
            )
        return lines

    async def _load_variant(self, variant_id: uuid.UUID) -> ProductVariant | None:
        result = await self._session.execute(
            select(ProductVariant).where(ProductVariant.id == variant_id)
        )
        return result.scalar_one_or_none()

    async def _check_availability(self, variant_id: uuid.UUID, quantity: int) -> int:
        """Rechaza la operación si no hay unidades suficientes; devuelve lo disponible.

        Se compara con el **disponible** (stock menos reservas), no con el total: lo reservado por
        otra persona no se puede vender.
        """
        levels = await InventoryService(self._session).availability_for([variant_id])
        available = levels[variant_id].available
        if quantity > available:
            raise AppError(
                status_code=409,
                code="insufficient_stock",
                detail=f"Only {available} units are available for this variant.",
            )
        return available

    async def _thumbnails(self, product_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        """Primera imagen de cada producto (la de menor `position`), en una sola consulta."""
        if not product_ids:
            return {}
        result = await self._session.execute(
            select(ProductImage.product_id, ProductImage.object_key)
            .where(ProductImage.product_id.in_(product_ids))
            .order_by(ProductImage.position)
        )
        thumbnails: dict[uuid.UUID, str] = {}
        for product_id, object_key in result.all():
            thumbnails.setdefault(product_id, object_key)
        return thumbnails

    async def _build(self, lines: list[CartLine]) -> CartOut:
        variant_ids = [line.variant.id for line in lines]
        # Todo en tres consultas (nada de N+1): stock disponible, imágenes y atributos.
        levels = await InventoryService(self._session).availability_for(variant_ids)
        thumbnails = await self._thumbnails([line.product.id for line in lines])
        values = await VariantValueRepository(self._session).list_for_variants(variant_ids)

        attributes: dict[uuid.UUID, list[VariantValueOut]] = {}
        for variant_id, attribute_id, name, value in values:
            attributes.setdefault(variant_id, []).append(
                VariantValueOut(attribute_id=attribute_id, name=name, value=value)
            )

        items: list[CartItemOut] = []
        subtotal = Decimal("0")
        total_items = 0

        for line in lines:
            variant, product, quantity = line.variant, line.product, line.quantity
            snapshot = line.unit_price_snapshot
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
                    available=levels[variant.id].available,
                    added_unit_price=snapshot,
                    # Solo se avisa si hay precio de referencia: sin él no se inventa nada.
                    price_changed=snapshot is not None and snapshot != variant.price,
                    thumbnail=thumbnails.get(product.id),
                    attribute_values=attributes.get(variant.id, []),
                )
            )

        return CartOut(
            items=items,
            total_items=total_items,
            subtotal=subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            currency=settings.DEFAULT_CURRENCY,
        )

    async def _guest_items(self, token: str | None) -> dict[str, tuple[int, Decimal | None]]:
        """Líneas del carrito de invitado: `{variant_id: (cantidad, precio al añadir)}`."""
        if not token:
            return {}
        data = await self._redis.hgetall(self._guest_key(token))
        lines: dict[str, tuple[int, Decimal | None]] = {}
        for field, value in data.items():
            raw = value.decode() if isinstance(value, bytes) else value
            lines[str(field)] = self._parse_guest_value(raw)
        return lines

    @staticmethod
    def _parse_guest_value(value: str) -> tuple[int, Decimal | None]:
        """Lee el valor de una línea de invitado.

        El formato actual es JSON (`quantity` + `unit_price`); los carritos guardados antes de este
        cambio tenían solo la cantidad, así que se sigue aceptando el número suelto.
        """
        try:
            payload = json.loads(value)
        except (TypeError, ValueError):
            return int(value), None
        if isinstance(payload, dict):
            raw_price = payload.get("unit_price")
            return int(payload.get("quantity", 0)), (
                Decimal(str(raw_price)) if raw_price else None
            )
        return int(payload), None

    @staticmethod
    def _guest_payload(quantity: int, unit_price: Decimal | None) -> str:
        """Valor que se guarda en Redis para una línea de invitado."""
        return json.dumps(
            {"quantity": quantity, "unit_price": str(unit_price) if unit_price else None}
        )

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
