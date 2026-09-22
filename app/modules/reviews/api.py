"""Endpoints del módulo de reseñas, preguntas y respuestas."""

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.modules.identity.deps import get_current_user
from app.modules.identity.models import User
from app.modules.reviews.schemas import (
    AnswerCreate,
    AnswerOut,
    QuestionCreate,
    QuestionListOut,
    QuestionOut,
    ReviewCreate,
    ReviewListOut,
    ReviewOut,
    ReviewUpdate,
)
from app.modules.reviews.service import ReviewService

router = APIRouter(tags=["reviews"])


def get_review_service(session: AsyncSession = Depends(get_session)) -> ReviewService:
    return ReviewService(session)


@router.post("/reviews", response_model=ReviewOut, status_code=status.HTTP_201_CREATED)
async def create_review(
    data: ReviewCreate,
    user: User = Depends(get_current_user),
    service: ReviewService = Depends(get_review_service),
) -> ReviewOut:
    """Reseña un producto que compraste y recibiste (una reseña por producto)."""
    return await service.create_review(user.id, data)


@router.get("/products/{product_id}/reviews", response_model=ReviewListOut)
async def list_product_reviews(
    product_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
    service: ReviewService = Depends(get_review_service),
) -> ReviewListOut:
    """Reseñas publicadas de un producto, con su nota media."""
    return await service.list_product_reviews(product_id, limit=limit, cursor=cursor)


@router.patch("/reviews/{review_id}", response_model=ReviewOut)
async def update_review(
    review_id: uuid.UUID,
    data: ReviewUpdate,
    user: User = Depends(get_current_user),
    service: ReviewService = Depends(get_review_service),
) -> ReviewOut:
    """Edita tu propia reseña."""
    return await service.update_review(user.id, review_id, data)


@router.delete("/reviews/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_review(
    review_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: ReviewService = Depends(get_review_service),
) -> Response:
    """Borra tu propia reseña (la reputación se recalcula)."""
    await service.delete_review(user.id, review_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/products/{product_id}/questions",
    response_model=QuestionOut,
    status_code=status.HTTP_201_CREATED,
)
async def ask_question(
    product_id: uuid.UUID,
    data: QuestionCreate,
    user: User = Depends(get_current_user),
    service: ReviewService = Depends(get_review_service),
) -> QuestionOut:
    """Pregunta públicamente algo sobre un producto."""
    return await service.ask_question(user.id, product_id, data.body)


@router.get("/products/{product_id}/questions", response_model=QuestionListOut)
async def list_product_questions(
    product_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    service: ReviewService = Depends(get_review_service),
) -> QuestionListOut:
    """Preguntas de un producto con las respuestas del vendedor."""
    return await service.list_product_questions(product_id, limit=limit)


@router.post(
    "/questions/{question_id}/answers",
    response_model=AnswerOut,
    status_code=status.HTTP_201_CREATED,
)
async def answer_question(
    question_id: uuid.UUID,
    data: AnswerCreate,
    user: User = Depends(get_current_user),
    service: ReviewService = Depends(get_review_service),
) -> AnswerOut:
    """Responde una pregunta (solo el vendedor dueño de la tienda del producto)."""
    return await service.answer_question(user.id, question_id, data.body)
