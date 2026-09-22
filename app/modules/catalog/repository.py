"""Repositorios del módulo de catálogo."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import (
    Attribute,
    Category,
    CategoryAttribute,
    Product,
    ProductImage,
    ProductVariant,
    VariantValue,
)


class CategoryRepository:
    """Acceso a categorías (respeta el borrado lógico)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, category_id: uuid.UUID) -> Category | None:
        result = await self._session.execute(
            select(Category).where(Category.id == category_id, Category.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Category | None:
        result = await self._session.execute(
            select(Category).where(Category.slug == slug, Category.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def add(self, category: Category) -> Category:
        self._session.add(category)
        await self._session.flush()
        return category

    async def list(self) -> list[Category]:
        result = await self._session.execute(
            select(Category).where(Category.deleted_at.is_(None)).order_by(Category.name)
        )
        return list(result.scalars().all())

    async def count_children(self, category_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(Category)
            .where(Category.parent_id == category_id, Category.deleted_at.is_(None))
        )
        return int(result.scalar_one())


class AttributeRepository:
    """Acceso a atributos (respeta el borrado lógico)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, attribute_id: uuid.UUID) -> Attribute | None:
        result = await self._session.execute(
            select(Attribute).where(Attribute.id == attribute_id, Attribute.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def add(self, attribute: Attribute) -> Attribute:
        self._session.add(attribute)
        await self._session.flush()
        return attribute

    async def list(self) -> list[Attribute]:
        result = await self._session.execute(
            select(Attribute).where(Attribute.deleted_at.is_(None)).order_by(Attribute.name)
        )
        return list(result.scalars().all())


class CategoryAttributeRepository:
    """Acceso a la relación categoría-atributo."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, category_id: uuid.UUID, attribute_id: uuid.UUID
    ) -> CategoryAttribute | None:
        result = await self._session.execute(
            select(CategoryAttribute).where(
                CategoryAttribute.category_id == category_id,
                CategoryAttribute.attribute_id == attribute_id,
            )
        )
        return result.scalar_one_or_none()

    async def add(self, link: CategoryAttribute) -> CategoryAttribute:
        self._session.add(link)
        await self._session.flush()
        return link

    async def delete(self, link: CategoryAttribute) -> None:
        await self._session.delete(link)

    async def list_for_category(
        self, category_id: uuid.UUID
    ) -> list[tuple[CategoryAttribute, Attribute]]:
        result = await self._session.execute(
            select(CategoryAttribute, Attribute)
            .join(Attribute, CategoryAttribute.attribute_id == Attribute.id)
            .where(CategoryAttribute.category_id == category_id, Attribute.deleted_at.is_(None))
            .order_by(Attribute.name)
        )
        return list(result.tuples().all())


class ProductRepository:
    """Acceso a productos (respeta el borrado lógico)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, product_id: uuid.UUID) -> Product | None:
        result = await self._session.execute(
            select(Product).where(Product.id == product_id, Product.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Product | None:
        result = await self._session.execute(
            select(Product).where(Product.slug == slug, Product.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def add(self, product: Product) -> Product:
        self._session.add(product)
        await self._session.flush()
        return product

    async def list_by_store(self, store_id: uuid.UUID) -> list[Product]:
        result = await self._session.execute(
            select(Product)
            .where(Product.store_id == store_id, Product.deleted_at.is_(None))
            .order_by(Product.created_at)
        )
        return list(result.scalars().all())


class ProductVariantRepository:
    """Acceso a variantes de producto."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_sku(self, sku: str) -> ProductVariant | None:
        result = await self._session.execute(
            select(ProductVariant).where(ProductVariant.sku == sku)
        )
        return result.scalar_one_or_none()

    async def add(self, variant: ProductVariant) -> ProductVariant:
        self._session.add(variant)
        await self._session.flush()
        return variant

    async def list_for_product(self, product_id: uuid.UUID) -> list[ProductVariant]:
        result = await self._session.execute(
            select(ProductVariant)
            .where(ProductVariant.product_id == product_id)
            .order_by(ProductVariant.created_at)
        )
        return list(result.scalars().all())


class ProductImageRepository:
    """Acceso a imágenes de producto."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, image: ProductImage) -> ProductImage:
        self._session.add(image)
        await self._session.flush()
        return image

    async def list_for_product(self, product_id: uuid.UUID) -> list[ProductImage]:
        result = await self._session.execute(
            select(ProductImage)
            .where(ProductImage.product_id == product_id)
            .order_by(ProductImage.position)
        )
        return list(result.scalars().all())

    async def delete(self, image: ProductImage) -> None:
        await self._session.delete(image)


class VariantValueRepository:
    """Acceso a valores de atributo por variante."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, value: VariantValue) -> VariantValue:
        self._session.add(value)
        await self._session.flush()
        return value
