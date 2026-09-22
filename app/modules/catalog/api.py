"""Endpoints del módulo de catálogo (categorías y atributos)."""

import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.modules.catalog.models import Attribute, Category, CategoryAttribute, ProductImage
from app.modules.catalog.schemas import (
    AttributeCreate,
    AttributeOut,
    CategoryAttributeAssign,
    CategoryAttributeLinkOut,
    CategoryAttributeOut,
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
    ImageAttachRequest,
    ImageUploadRequest,
    ProductCreate,
    ProductImageOut,
    ProductOut,
    ProductUpdate,
    UploadUrlOut,
)
from app.modules.catalog.service import CatalogService, ProductService
from app.modules.identity.deps import require_roles
from app.modules.identity.models import User, UserRole
from app.modules.sellers.deps import get_approved_store
from app.modules.sellers.models import Store

router = APIRouter(tags=["catalog"])


def get_catalog_service(session: AsyncSession = Depends(get_session)) -> CatalogService:
    return CatalogService(session)


# ---------- Categorías (lectura pública, escritura admin) ----------


@router.get("/catalog/categories", response_model=list[CategoryOut])
async def list_categories(
    service: CatalogService = Depends(get_catalog_service),
) -> list[Category]:
    return await service.list_categories()


@router.post(
    "/catalog/categories",
    response_model=CategoryOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_category(
    data: CategoryCreate,
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
    service: CatalogService = Depends(get_catalog_service),
) -> Category:
    return await service.create_category(data)


@router.patch("/catalog/categories/{category_id}", response_model=CategoryOut)
async def update_category(
    category_id: uuid.UUID,
    data: CategoryUpdate,
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
    service: CatalogService = Depends(get_catalog_service),
) -> Category:
    return await service.update_category(category_id, data)


@router.delete("/catalog/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: uuid.UUID,
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
    service: CatalogService = Depends(get_catalog_service),
) -> Response:
    await service.delete_category(category_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- Atributos ----------


@router.get("/catalog/attributes", response_model=list[AttributeOut])
async def list_attributes(
    service: CatalogService = Depends(get_catalog_service),
) -> list[Attribute]:
    return await service.list_attributes()


@router.post(
    "/catalog/attributes",
    response_model=AttributeOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_attribute(
    data: AttributeCreate,
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
    service: CatalogService = Depends(get_catalog_service),
) -> Attribute:
    return await service.create_attribute(data)


# ---------- Atributos por categoría ----------


@router.get(
    "/catalog/categories/{category_id}/attributes",
    response_model=list[CategoryAttributeOut],
)
async def list_category_attributes(
    category_id: uuid.UUID,
    service: CatalogService = Depends(get_catalog_service),
) -> list[CategoryAttributeOut]:
    return await service.list_category_attributes(category_id)


@router.post(
    "/catalog/categories/{category_id}/attributes",
    response_model=CategoryAttributeLinkOut,
    status_code=status.HTTP_201_CREATED,
)
async def assign_attribute(
    category_id: uuid.UUID,
    data: CategoryAttributeAssign,
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
    service: CatalogService = Depends(get_catalog_service),
) -> CategoryAttribute:
    return await service.assign_attribute(category_id, data)


@router.delete(
    "/catalog/categories/{category_id}/attributes/{attribute_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unassign_attribute(
    category_id: uuid.UUID,
    attribute_id: uuid.UUID,
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
    service: CatalogService = Depends(get_catalog_service),
) -> Response:
    await service.unassign_attribute(category_id, attribute_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- Productos, variantes e imágenes ----------


def get_product_service(session: AsyncSession = Depends(get_session)) -> ProductService:
    return ProductService(session)


@router.get("/catalog/products", response_model=list[ProductOut])
async def list_products(
    store: Store = Depends(get_approved_store),
    service: ProductService = Depends(get_product_service),
) -> list[ProductOut]:
    return await service.list_products(store.id)


@router.post(
    "/catalog/products",
    response_model=ProductOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_product(
    data: ProductCreate,
    store: Store = Depends(get_approved_store),
    service: ProductService = Depends(get_product_service),
) -> ProductOut:
    return await service.create_product(store.id, data)


@router.get("/catalog/products/{product_id}", response_model=ProductOut)
async def get_product(
    product_id: uuid.UUID,
    service: ProductService = Depends(get_product_service),
) -> ProductOut:
    return await service.get_product(product_id)


@router.patch("/catalog/products/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: uuid.UUID,
    data: ProductUpdate,
    store: Store = Depends(get_approved_store),
    service: ProductService = Depends(get_product_service),
) -> ProductOut:
    return await service.update_product(product_id, store.id, data)


@router.delete("/catalog/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: uuid.UUID,
    store: Store = Depends(get_approved_store),
    service: ProductService = Depends(get_product_service),
) -> Response:
    await service.delete_product(product_id, store.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/catalog/products/{product_id}/publish", response_model=ProductOut)
async def publish_product(
    product_id: uuid.UUID,
    store: Store = Depends(get_approved_store),
    service: ProductService = Depends(get_product_service),
) -> ProductOut:
    return await service.publish(product_id, store.id)


@router.post("/catalog/products/{product_id}/pause", response_model=ProductOut)
async def pause_product(
    product_id: uuid.UUID,
    store: Store = Depends(get_approved_store),
    service: ProductService = Depends(get_product_service),
) -> ProductOut:
    return await service.pause(product_id, store.id)


@router.post("/catalog/products/{product_id}/close", response_model=ProductOut)
async def close_product(
    product_id: uuid.UUID,
    store: Store = Depends(get_approved_store),
    service: ProductService = Depends(get_product_service),
) -> ProductOut:
    return await service.close(product_id, store.id)


@router.post("/catalog/images/upload-url", response_model=UploadUrlOut)
async def request_upload_url(
    data: ImageUploadRequest,
    _store: Store = Depends(get_approved_store),
    service: ProductService = Depends(get_product_service),
) -> UploadUrlOut:
    return service.generate_upload_url(data)


@router.get("/catalog/products/{product_id}/images", response_model=list[ProductImageOut])
async def list_images(
    product_id: uuid.UUID,
    service: ProductService = Depends(get_product_service),
) -> list[ProductImage]:
    return await service.list_images(product_id)


@router.post(
    "/catalog/products/{product_id}/images",
    response_model=ProductImageOut,
    status_code=status.HTTP_201_CREATED,
)
async def attach_image(
    product_id: uuid.UUID,
    data: ImageAttachRequest,
    store: Store = Depends(get_approved_store),
    service: ProductService = Depends(get_product_service),
) -> ProductImage:
    return await service.attach_image(product_id, store.id, data)


@router.delete(
    "/catalog/products/{product_id}/images/{image_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_image(
    product_id: uuid.UUID,
    image_id: uuid.UUID,
    store: Store = Depends(get_approved_store),
    service: ProductService = Depends(get_product_service),
) -> Response:
    await service.delete_image(product_id, store.id, image_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
