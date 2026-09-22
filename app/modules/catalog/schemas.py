"""Schemas Pydantic del módulo de catálogo (categorías y atributos)."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.catalog.models import AttributeType, ProductStatus


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    parent_id: uuid.UUID | None = None
    commission_rate: Decimal | None = Field(default=None, ge=0, le=100)


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    parent_id: uuid.UUID | None = None
    commission_rate: Decimal | None = Field(default=None, ge=0, le=100)


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str
    slug: str
    commission_rate: Decimal | None
    created_at: datetime


class AttributeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: AttributeType


class AttributeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    type: AttributeType
    created_at: datetime


class CategoryAttributeAssign(BaseModel):
    attribute_id: uuid.UUID
    is_required: bool = False


class CategoryAttributeOut(BaseModel):
    attribute_id: uuid.UUID
    name: str
    type: AttributeType
    is_required: bool


class CategoryAttributeLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category_id: uuid.UUID
    attribute_id: uuid.UUID
    is_required: bool


# ---------- Productos, variantes e imágenes ----------


class VariantValueIn(BaseModel):
    attribute_id: uuid.UUID
    value: str = Field(min_length=1, max_length=255)


class VariantIn(BaseModel):
    sku: str = Field(min_length=1, max_length=100)
    price: Decimal = Field(gt=0)
    compare_at_price: Decimal | None = Field(default=None, gt=0)
    stock: int = Field(default=0, ge=0)
    attribute_values: list[VariantValueIn] = Field(default_factory=list)


class ProductCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    brand: str | None = Field(default=None, max_length=120)
    category_id: uuid.UUID
    variants: list[VariantIn] = Field(default_factory=list)


class ProductUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    brand: str | None = Field(default=None, max_length=120)


class VariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sku: str
    price: Decimal
    compare_at_price: Decimal | None


class ProductImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    object_key: str
    position: int
    alt: str | None


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    store_id: uuid.UUID
    category_id: uuid.UUID
    title: str
    slug: str
    description: str | None
    brand: str | None
    status: ProductStatus
    created_at: datetime
    variants: list[VariantOut] = Field(default_factory=list)
    images: list[ProductImageOut] = Field(default_factory=list)


class ImageUploadRequest(BaseModel):
    content_type: str = "image/jpeg"
    extension: str = ""


class UploadUrlOut(BaseModel):
    object_key: str
    upload_url: str


class ImageAttachRequest(BaseModel):
    object_key: str
    alt: str | None = Field(default=None, max_length=200)
    position: int = Field(default=0, ge=0)
