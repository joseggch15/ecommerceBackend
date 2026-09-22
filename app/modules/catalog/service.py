"""Lógica de negocio del módulo de catálogo (categorías y atributos)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.storage import generate_presigned_upload_url, new_object_key
from app.modules.catalog.models import (
    Attribute,
    Category,
    CategoryAttribute,
    Product,
    ProductImage,
    ProductStatus,
    ProductVariant,
    VariantValue,
)
from app.modules.catalog.repository import (
    AttributeRepository,
    CategoryAttributeRepository,
    CategoryRepository,
    ProductImageRepository,
    ProductRepository,
    ProductVariantRepository,
    VariantValueRepository,
)
from app.modules.catalog.schemas import (
    AttributeCreate,
    CategoryAttributeAssign,
    CategoryAttributeOut,
    CategoryCreate,
    CategoryUpdate,
    ImageAttachRequest,
    ImageUploadRequest,
    ProductCreate,
    ProductImageOut,
    ProductOut,
    ProductUpdate,
    UploadUrlOut,
    VariantIn,
    VariantOut,
    VariantValueOut,
)
from app.modules.inventory.service import InventoryService
from app.modules.shipping.estimates import ShippingEstimateOut, estimate_shipping
from app.shared.text import slugify


class CatalogService:
    """Casos de uso de categorías y atributos."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._categories = CategoryRepository(session)
        self._attributes = AttributeRepository(session)
        self._links = CategoryAttributeRepository(session)

    # ---------- Categorías ----------

    async def create_category(self, data: CategoryCreate) -> Category:
        if data.parent_id is not None:
            await self._ensure_category(data.parent_id)

        category = Category(
            name=data.name,
            slug=await self._unique_slug(data.name),
            parent_id=data.parent_id,
            commission_rate=data.commission_rate,
        )
        await self._categories.add(category)
        await self._session.commit()
        return category

    async def list_categories(self) -> list[Category]:
        return await self._categories.list()

    async def update_category(self, category_id: uuid.UUID, data: CategoryUpdate) -> Category:
        category = await self._categories.get_by_id(category_id)
        if category is None:
            raise AppError(404, "category_not_found", "Category not found.")

        if data.name is not None:
            category.name = data.name
            category.slug = await self._unique_slug(data.name, exclude_id=category.id)

        if data.parent_id is not None:
            if data.parent_id == category.id:
                raise AppError(400, "invalid_parent", "A category cannot be its own parent.")
            await self._ensure_category(data.parent_id)
            category.parent_id = data.parent_id

        if data.commission_rate is not None:
            category.commission_rate = data.commission_rate

        await self._session.commit()
        return category

    async def delete_category(self, category_id: uuid.UUID) -> None:
        category = await self._categories.get_by_id(category_id)
        if category is None:
            raise AppError(404, "category_not_found", "Category not found.")

        children = await self._categories.count_children(category_id)
        if children > 0:
            raise AppError(409, "category_has_children", "Delete child categories first.")

        category.deleted_at = datetime.now(UTC)
        await self._session.commit()

    # ---------- Atributos ----------

    async def create_attribute(self, data: AttributeCreate) -> Attribute:
        attribute = Attribute(name=data.name, type=data.type)
        await self._attributes.add(attribute)
        await self._session.commit()
        return attribute

    async def list_attributes(self) -> list[Attribute]:
        return await self._attributes.list()

    # ---------- Atributos por categoría ----------

    async def assign_attribute(
        self, category_id: uuid.UUID, data: CategoryAttributeAssign
    ) -> CategoryAttribute:
        await self._ensure_category(category_id)
        attribute = await self._attributes.get_by_id(data.attribute_id)
        if attribute is None:
            raise AppError(404, "attribute_not_found", "Attribute not found.")

        existing = await self._links.get(category_id, data.attribute_id)
        if existing is not None:
            raise AppError(409, "attribute_already_assigned", "Attribute already assigned.")

        link = CategoryAttribute(
            category_id=category_id,
            attribute_id=data.attribute_id,
            is_required=data.is_required,
        )
        await self._links.add(link)
        await self._session.commit()
        return link

    async def unassign_attribute(self, category_id: uuid.UUID, attribute_id: uuid.UUID) -> None:
        link = await self._links.get(category_id, attribute_id)
        if link is None:
            raise AppError(404, "attribute_not_assigned", "Attribute is not assigned.")
        await self._links.delete(link)
        await self._session.commit()

    async def list_category_attributes(self, category_id: uuid.UUID) -> list[CategoryAttributeOut]:
        await self._ensure_category(category_id)
        rows = await self._links.list_for_category(category_id)
        return [
            CategoryAttributeOut(
                attribute_id=attribute.id,
                name=attribute.name,
                type=attribute.type,
                is_required=link.is_required,
            )
            for link, attribute in rows
        ]

    # ---------- Helpers ----------

    async def _ensure_category(self, category_id: uuid.UUID) -> None:
        if await self._categories.get_by_id(category_id) is None:
            raise AppError(404, "category_not_found", "Category not found.")

    async def _unique_slug(self, name: str, exclude_id: uuid.UUID | None = None) -> str:
        base = slugify(name)
        candidate = base
        counter = 1
        while True:
            existing = await self._categories.get_by_slug(candidate)
            if existing is None or (exclude_id is not None and existing.id == exclude_id):
                return candidate
            counter += 1
            candidate = f"{base}-{counter}"


class ProductService:
    """Casos de uso de productos, variantes e imágenes."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._products = ProductRepository(session)
        self._variants = ProductVariantRepository(session)
        self._images = ProductImageRepository(session)
        self._values = VariantValueRepository(session)
        self._categories = CategoryRepository(session)

    async def create_product(self, store_id: uuid.UUID, data: ProductCreate) -> ProductOut:
        if await self._categories.get_by_id(data.category_id) is None:
            raise AppError(404, "category_not_found", "Category not found.")

        product = Product(
            store_id=store_id,
            category_id=data.category_id,
            title=data.title,
            slug=await self._unique_slug(data.title),
            description=data.description,
            brand=data.brand,
        )
        await self._products.add(product)

        for variant_data in data.variants:
            await self._add_variant(product.id, variant_data)

        await self._session.commit()
        return await self._to_out(product)

    async def get_product(self, product_id: uuid.UUID) -> ProductOut:
        product = await self._products.get_by_id(product_id)
        if product is None:
            raise AppError(404, "product_not_found", "Product not found.")
        return await self._to_out(product)

    async def get_product_by_slug(self, slug: str) -> ProductOut:
        """Producto por su slug (consulta por índice único, pública)."""
        product = await self._products.get_by_slug(slug)
        if product is None:
            raise AppError(404, "product_not_found", "Product not found.")
        return await self._to_out(product)

    async def list_products(self, store_id: uuid.UUID) -> list[ProductOut]:
        products = await self._products.list_by_store(store_id)
        return [await self._to_out(p) for p in products]

    async def update_product(
        self, product_id: uuid.UUID, store_id: uuid.UUID, data: ProductUpdate
    ) -> ProductOut:
        product = await self._get_owned(product_id, store_id)
        if data.title is not None:
            product.title = data.title
            product.slug = await self._unique_slug(data.title, exclude_id=product.id)
        if data.description is not None:
            product.description = data.description
        if data.brand is not None:
            product.brand = data.brand
        await self._session.commit()
        return await self._to_out(product)

    async def delete_product(self, product_id: uuid.UUID, store_id: uuid.UUID) -> None:
        product = await self._get_owned(product_id, store_id)
        product.deleted_at = datetime.now(UTC)
        await self._session.commit()

    async def publish(self, product_id: uuid.UUID, store_id: uuid.UUID) -> ProductOut:
        product = await self._get_owned(product_id, store_id)
        if product.status != ProductStatus.DRAFT:
            raise AppError(409, "invalid_product_status", "Only draft products can be published.")
        product.status = ProductStatus.ACTIVE
        await self._session.commit()
        return await self._to_out(product)

    async def pause(self, product_id: uuid.UUID, store_id: uuid.UUID) -> ProductOut:
        product = await self._get_owned(product_id, store_id)
        if product.status != ProductStatus.ACTIVE:
            raise AppError(409, "invalid_product_status", "Only active products can be paused.")
        product.status = ProductStatus.PAUSED
        await self._session.commit()
        return await self._to_out(product)

    async def close(self, product_id: uuid.UUID, store_id: uuid.UUID) -> ProductOut:
        product = await self._get_owned(product_id, store_id)
        if product.status == ProductStatus.CLOSED:
            raise AppError(409, "invalid_product_status", "Product is already closed.")
        product.status = ProductStatus.CLOSED
        await self._session.commit()
        return await self._to_out(product)

    def generate_upload_url(self, data: ImageUploadRequest) -> UploadUrlOut:
        object_key = new_object_key(data.extension)
        upload_url = generate_presigned_upload_url(object_key, data.content_type)
        return UploadUrlOut(object_key=object_key, upload_url=upload_url)

    async def attach_image(
        self, product_id: uuid.UUID, store_id: uuid.UUID, data: ImageAttachRequest
    ) -> ProductImage:
        await self._get_owned(product_id, store_id)
        image = ProductImage(
            product_id=product_id,
            object_key=data.object_key,
            position=data.position,
            alt=data.alt,
        )
        await self._images.add(image)
        await self._session.commit()
        return image

    async def list_images(self, product_id: uuid.UUID) -> list[ProductImage]:
        return await self._images.list_for_product(product_id)

    async def shipping_estimate(
        self, product_id: uuid.UUID, country: str | None = None
    ) -> ShippingEstimateOut:
        """Estimación de entrega del producto (pública).

        No es una tarifa de transportadora: hoy no existe (decisión 0012). Es una estimación
        configurable y el propio objeto lo declara con `source`, para que la interfaz la muestre
        como aproximada.
        """
        product = await self._products.get_by_id(product_id)
        if product is None:
            raise AppError(404, "product_not_found", "Product not found.")

        return estimate_shipping(
            product_id=product.id, store_id=product.store_id, country=country
        )

    async def delete_image(
        self, product_id: uuid.UUID, store_id: uuid.UUID, image_id: uuid.UUID
    ) -> None:
        await self._get_owned(product_id, store_id)
        images = await self._images.list_for_product(product_id)
        image = next((img for img in images if img.id == image_id), None)
        if image is None:
            raise AppError(404, "image_not_found", "Image not found.")
        await self._images.delete(image)
        await self._session.commit()

    async def _add_variant(self, product_id: uuid.UUID, data: VariantIn) -> None:
        if await self._variants.get_by_sku(data.sku) is not None:
            raise AppError(409, "sku_already_exists", f"SKU '{data.sku}' already exists.")
        variant = ProductVariant(
            product_id=product_id,
            sku=data.sku,
            price=data.price,
            compare_at_price=data.compare_at_price,
        )
        await self._variants.add(variant)
        await InventoryService(self._session).ensure_item(variant.id, data.stock)
        for value_data in data.attribute_values:
            await self._values.add(
                VariantValue(
                    variant_id=variant.id,
                    attribute_id=value_data.attribute_id,
                    value=value_data.value,
                )
            )

    async def _get_owned(self, product_id: uuid.UUID, store_id: uuid.UUID) -> Product:
        product = await self._products.get_by_id(product_id)
        if product is None:
            raise AppError(404, "product_not_found", "Product not found.")
        if product.store_id != store_id:
            raise AppError(403, "forbidden", "You do not own this product.")
        return product

    async def _to_out(self, product: Product) -> ProductOut:
        variants = await self._variants.list_for_product(product.id)
        images = await self._images.list_for_product(product.id)
        variant_ids = [variant.id for variant in variants]
        # Stock y atributos de todas las variantes en dos consultas (nada de N+1): lo que necesita
        # la ficha para mostrar «Talla: M» y las unidades reales de cada presentación.
        levels = await InventoryService(self._session).availability_for(variant_ids)
        values = await self._values.list_for_variants(variant_ids)

        attributes: dict[uuid.UUID, list[VariantValueOut]] = {}
        for variant_id, attribute_id, name, value in values:
            attributes.setdefault(variant_id, []).append(
                VariantValueOut(attribute_id=attribute_id, name=name, value=value)
            )

        variant_out = [
            VariantOut(
                id=variant.id,
                sku=variant.sku,
                price=variant.price,
                compare_at_price=variant.compare_at_price,
                stock=levels[variant.id].quantity,
                available=levels[variant.id].available,
                attribute_values=attributes.get(variant.id, []),
            )
            for variant in variants
        ]

        return ProductOut(
            id=product.id,
            store_id=product.store_id,
            category_id=product.category_id,
            title=product.title,
            slug=product.slug,
            description=product.description,
            brand=product.brand,
            status=product.status,
            created_at=product.created_at,
            total_available=sum(item.available for item in variant_out),
            variants=variant_out,
            images=[ProductImageOut.model_validate(img) for img in images],
        )

    async def _unique_slug(self, title: str, exclude_id: uuid.UUID | None = None) -> str:
        base = slugify(title)
        candidate = base
        counter = 1
        while True:
            existing = await self._products.get_by_slug(candidate)
            if existing is None or (exclude_id is not None and existing.id == exclude_id):
                return candidate
            counter += 1
            candidate = f"{base}-{counter}"
