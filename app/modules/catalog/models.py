"""Modelos ORM del módulo de catálogo (categorías y atributos)."""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.base import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin, enum_values


class AttributeType(enum.StrEnum):
    """Tipo de valor de un atributo."""

    TEXT = "text"
    NUMBER = "number"
    SELECT = "select"


class Category(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Categoría jerárquica (árbol) con comisión opcional."""

    __tablename__ = "categories"

    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(140), unique=True, index=True, nullable=False)
    commission_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)


class Attribute(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Atributo de producto (talla, color, material...)."""

    __tablename__ = "attributes"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[AttributeType] = mapped_column(
        Enum(AttributeType, name="attribute_type", native_enum=False, values_callable=enum_values),
        nullable=False,
    )


class CategoryAttribute(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Relación entre una categoría y sus atributos."""

    __tablename__ = "category_attributes"
    __table_args__ = (
        UniqueConstraint("category_id", "attribute_id", name="uq_category_attribute"),
    )

    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    attribute_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attributes.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    is_required: Mapped[bool] = mapped_column(default=False, nullable=False)


class ProductStatus(enum.StrEnum):
    """Estado de publicación de un producto."""

    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"


class Product(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Producto publicado por un vendedor en una categoría."""

    __tablename__ = "products"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stores.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(220), unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[ProductStatus] = mapped_column(
        Enum(ProductStatus, name="product_status", native_enum=False, values_callable=enum_values),
        nullable=False,
        default=ProductStatus.DRAFT,
    )


class ProductVariant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Variante de un producto (SKU, precio y stock)."""

    __tablename__ = "product_variants"

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    sku: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    compare_at_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)


class ProductImage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Imagen de un producto (objeto en el storage S3/MinIO)."""

    __tablename__ = "product_images"

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    object_key: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    position: Mapped[int] = mapped_column(default=0, nullable=False)
    alt: Mapped[str | None] = mapped_column(String(200), nullable=True)


class VariantValue(UUIDPrimaryKeyMixin, Base):
    """Valor de un atributo para una variante (EAV)."""

    __tablename__ = "variant_values"
    __table_args__ = (UniqueConstraint("variant_id", "attribute_id", name="uq_variant_attribute"),)

    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("product_variants.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    attribute_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attributes.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
