"""Endpoints del módulo de administración (moderación, métricas y auditoría)."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.modules.admin.schemas import AdminActionOut, MetricsOut, ModerationIn
from app.modules.admin.service import AdminService
from app.modules.identity.deps import require_roles
from app.modules.identity.models import User, UserRole

router = APIRouter(prefix="/admin", tags=["admin"])

ADMIN_ONLY = Depends(require_roles(UserRole.ADMIN))


def get_admin_service(session: AsyncSession = Depends(get_session)) -> AdminService:
    return AdminService(session)


@router.post("/products/{product_id}/suspend", response_model=AdminActionOut)
async def suspend_product(
    product_id: uuid.UUID,
    data: ModerationIn | None = None,
    admin: User = ADMIN_ONLY,
    service: AdminService = Depends(get_admin_service),
) -> AdminActionOut:
    """Pausa un producto (queda fuera de la venta)."""
    return await service.moderate_product(
        admin.id, product_id, suspend=True, reason=data.reason if data else None
    )


@router.post("/products/{product_id}/restore", response_model=AdminActionOut)
async def restore_product(
    product_id: uuid.UUID,
    data: ModerationIn | None = None,
    admin: User = ADMIN_ONLY,
    service: AdminService = Depends(get_admin_service),
) -> AdminActionOut:
    """Reactiva un producto pausado."""
    return await service.moderate_product(
        admin.id, product_id, suspend=False, reason=data.reason if data else None
    )


@router.post("/stores/{store_id}/suspend", response_model=AdminActionOut)
async def suspend_store(
    store_id: uuid.UUID,
    data: ModerationIn | None = None,
    admin: User = ADMIN_ONLY,
    service: AdminService = Depends(get_admin_service),
) -> AdminActionOut:
    """Suspende la tienda de un vendedor."""
    return await service.moderate_store(
        admin.id, store_id, suspend=True, reason=data.reason if data else None
    )


@router.post("/stores/{store_id}/restore", response_model=AdminActionOut)
async def restore_store(
    store_id: uuid.UUID,
    data: ModerationIn | None = None,
    admin: User = ADMIN_ONLY,
    service: AdminService = Depends(get_admin_service),
) -> AdminActionOut:
    """Reactiva (aprueba) una tienda suspendida."""
    return await service.moderate_store(
        admin.id, store_id, suspend=False, reason=data.reason if data else None
    )


@router.post("/reviews/{review_id}/hide", response_model=AdminActionOut)
async def hide_review(
    review_id: uuid.UUID,
    data: ModerationIn | None = None,
    admin: User = ADMIN_ONLY,
    service: AdminService = Depends(get_admin_service),
) -> AdminActionOut:
    """Oculta una reseña (recalcula la reputación)."""
    return await service.moderate_review(
        admin.id, review_id, hide=True, reason=data.reason if data else None
    )


@router.post("/reviews/{review_id}/publish", response_model=AdminActionOut)
async def publish_review(
    review_id: uuid.UUID,
    data: ModerationIn | None = None,
    admin: User = ADMIN_ONLY,
    service: AdminService = Depends(get_admin_service),
) -> AdminActionOut:
    """Republica una reseña oculta."""
    return await service.moderate_review(
        admin.id, review_id, hide=False, reason=data.reason if data else None
    )


@router.get("/metrics", response_model=MetricsOut)
async def get_metrics(
    _admin: User = ADMIN_ONLY,
    service: AdminService = Depends(get_admin_service),
) -> MetricsOut:
    """Tablero: GMV, comisión acumulada, órdenes por estado y top vendedores."""
    return await service.metrics()


@router.get("/actions", response_model=list[AdminActionOut])
async def list_actions(
    limit: int = Query(default=50, ge=1, le=200),
    _admin: User = ADMIN_ONLY,
    service: AdminService = Depends(get_admin_service),
) -> list[AdminActionOut]:
    """Libro de auditoría de acciones administrativas."""
    return await service.list_actions(limit=limit)
