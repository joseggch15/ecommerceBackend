"""Endpoints del módulo de administración (moderación, métricas y auditoría)."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.modules.admin.schemas import (
    AdminActionOut,
    AdminQuestionListOut,
    AdminUserListOut,
    MetricsOut,
    ModerationIn,
)
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


@router.get("/users", response_model=AdminUserListOut)
async def list_users(
    q: str | None = Query(
        default=None,
        max_length=320,
        description="Busca por correo (contiene). Sin valor, lista todas las cuentas.",
    ),
    role: UserRole | None = Query(
        default=None,
        description="Filtra por rol de plataforma (`customer` o `admin`).",
    ),
    cursor: str | None = Query(
        default=None, description="Cursor de la página anterior (`next_cursor`)."
    ),
    limit: int = Query(default=20, ge=1, le=100),
    _admin: User = ADMIN_ONLY,
    service: AdminService = Depends(get_admin_service),
) -> AdminUserListOut:
    """Directorio de usuarios (solo administradores), paginado por cursor.

    Búsqueda por correo (`q`, contiene) y filtro por rol (`role`). Cada usuario trae correo, rol,
    si verificó su correo, su nombre y, si tiene tienda, su tienda y su estado (**no hay rol
    «vendedor»**: es un usuario con tienda). Las cuentas borradas lógicamente no aparecen.

    Nunca devuelve hashes de contraseña ni tokens: esos campos no se consultan siquiera.
    """
    return await service.list_users(q=q, role=role, cursor=cursor, limit=limit)


@router.get("/questions", response_model=AdminQuestionListOut)
async def list_questions(
    published: bool | None = Query(
        default=None,
        description="Filtra por visibilidad: `true` publicadas, `false` ocultas, sin valor todas.",
    ),
    cursor: str | None = Query(
        default=None, description="Cursor de la página anterior (`next_cursor`)."
    ),
    limit: int = Query(default=20, ge=1, le=100),
    _admin: User = ADMIN_ONLY,
    service: AdminService = Depends(get_admin_service),
) -> AdminQuestionListOut:
    """Preguntas de toda la plataforma para moderar (solo administradores), por cursor.

    Es el equivalente del listado de reseñas para las preguntas: sin él habría que adivinar el id
    para poder ocultar algo. Incluye las ocultas, con el título del producto al que pertenecen y el
    número de respuestas, del más reciente al más antiguo.
    """
    return await service.list_questions(published=published, cursor=cursor, limit=limit)


@router.post("/questions/{question_id}/hide", response_model=AdminActionOut)
async def hide_question(
    question_id: uuid.UUID,
    data: ModerationIn | None = None,
    admin: User = ADMIN_ONLY,
    service: AdminService = Depends(get_admin_service),
) -> AdminActionOut:
    """Oculta una pregunta (y sus respuestas) del listado público del producto."""
    return await service.moderate_question(
        admin.id, question_id, hide=True, reason=data.reason if data else None
    )


@router.post("/questions/{question_id}/publish", response_model=AdminActionOut)
async def publish_question(
    question_id: uuid.UUID,
    data: ModerationIn | None = None,
    admin: User = ADMIN_ONLY,
    service: AdminService = Depends(get_admin_service),
) -> AdminActionOut:
    """Republica una pregunta oculta (mismo verbo que las reseñas: ocultar / publicar)."""
    return await service.moderate_question(
        admin.id, question_id, hide=False, reason=data.reason if data else None
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
