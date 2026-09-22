"""Lógica de negocio del módulo de reseñas, preguntas y reputación.

Reglas:
- Solo puede reseñar quien compró el producto y **lo recibió** (`seller_orders.status = delivered`).
- Una reseña por comprador y producto; el agregado de reputación se recalcula al
  crear, editar o borrar.
- Las preguntas las responde el vendedor dueño de la tienda del producto.
"""

import base64
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.catalog.models import Product
from app.modules.reviews.models import Answer, Question, Review
from app.modules.reviews.repository import QuestionRepository, ReviewRepository
from app.modules.reviews.schemas import (
    AnswerOut,
    QuestionListOut,
    QuestionOut,
    ReviewCreate,
    ReviewListOut,
    ReviewOut,
    ReviewUpdate,
)
from app.modules.sellers.models import Store


def _encode_cursor(created_at: datetime, item_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(f"{created_at.isoformat()}|{item_id}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        value, item_id = raw.rsplit("|", 1)
        return datetime.fromisoformat(value), uuid.UUID(item_id)
    except (ValueError, UnicodeDecodeError):
        raise AppError(400, "invalid_cursor", "Invalid cursor.") from None


def _review_out(review: Review) -> ReviewOut:
    return ReviewOut(
        id=review.id,
        product_id=review.product_id,
        user_id=review.user_id,
        store_id=review.store_id,
        rating=review.rating,
        title=review.title,
        body=review.body,
        verified_purchase=review.order_item_id is not None,
        created_at=review.created_at,
        updated_at=review.updated_at,
    )


def _answer_out(answer: Answer) -> AnswerOut:
    return AnswerOut(
        id=answer.id, store_id=answer.store_id, body=answer.body, created_at=answer.created_at
    )


class ReviewService:
    """Reseñas, reputación y preguntas/respuestas."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._reviews = ReviewRepository(session)
        self._questions = QuestionRepository(session)

    async def create_review(self, user_id: uuid.UUID, data: ReviewCreate) -> ReviewOut:
        """Crea la reseña de un producto comprado y recibido."""
        product = await self._product(data.product_id)
        if await self._reviews.get_by_user_product(user_id, product.id) is not None:
            raise AppError(409, "review_exists", "You already reviewed this product.")

        order_item_id = await self._reviews.delivered_order_item_id(user_id, product.id)
        if order_item_id is None:
            raise AppError(403, "purchase_required", "You can only review products you received.")

        review = await self._reviews.add(
            Review(
                product_id=product.id,
                user_id=user_id,
                store_id=product.store_id,
                order_item_id=order_item_id,
                rating=data.rating,
                title=data.title,
                body=data.body,
            )
        )
        await self._refresh_reputation(product.id, product.store_id)
        await self._session.commit()
        return _review_out(review)

    async def list_product_reviews(
        self, product_id: uuid.UUID, *, limit: int, cursor: str | None
    ) -> ReviewListOut:
        """Reseñas publicadas de un producto (más recientes primero)."""
        await self._product(product_id)
        decoded = _decode_cursor(cursor) if cursor else None
        rows = await self._reviews.list_by_product(product_id, limit=limit + 1, cursor=decoded)
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = (
            _encode_cursor(page[-1].created_at, page[-1].id) if has_more and page else None
        )
        average, count = await self._reviews.stats_for_product(product_id)
        return ReviewListOut(
            items=[_review_out(review) for review in page],
            next_cursor=next_cursor,
            rating_average=average,
            rating_count=count,
        )

    async def update_review(
        self, user_id: uuid.UUID, review_id: uuid.UUID, data: ReviewUpdate
    ) -> ReviewOut:
        """Edita la propia reseña."""
        review = await self._owned_review(user_id, review_id)
        if data.rating is not None:
            review.rating = data.rating
        if data.title is not None:
            review.title = data.title
        if data.body is not None:
            review.body = data.body
        await self._refresh_reputation(review.product_id, review.store_id)
        await self._session.commit()
        await self._session.refresh(review)
        return _review_out(review)

    async def delete_review(self, user_id: uuid.UUID, review_id: uuid.UUID) -> None:
        """Borra la propia reseña y recalcula la reputación."""
        review = await self._owned_review(user_id, review_id)
        product_id, store_id = review.product_id, review.store_id
        await self._reviews.delete(review)
        await self._refresh_reputation(product_id, store_id)
        await self._session.commit()

    async def ask_question(
        self, user_id: uuid.UUID, product_id: uuid.UUID, body: str
    ) -> QuestionOut:
        """Publica una pregunta sobre un producto."""
        product = await self._product(product_id)
        question = await self._questions.add(
            Question(product_id=product.id, user_id=user_id, body=body)
        )
        await self._session.commit()
        return QuestionOut(
            id=question.id,
            product_id=question.product_id,
            user_id=question.user_id,
            body=question.body,
            created_at=question.created_at,
            answers=[],
        )

    async def list_product_questions(
        self, product_id: uuid.UUID, *, limit: int, cursor: str | None = None
    ) -> QuestionListOut:
        """Preguntas publicadas de un producto, con sus respuestas (paginación por cursor)."""
        await self._product(product_id)
        decoded = _decode_cursor(cursor) if cursor else None
        questions = await self._questions.list_by_product(
            product_id, limit=limit + 1, cursor=decoded
        )
        has_more = len(questions) > limit
        page = questions[:limit]
        next_cursor = (
            _encode_cursor(page[-1].created_at, page[-1].id) if has_more and page else None
        )
        answers = await self._questions.list_answers([question.id for question in page])

        grouped: dict[uuid.UUID, list[AnswerOut]] = {}
        for answer in answers:
            grouped.setdefault(answer.question_id, []).append(_answer_out(answer))

        return QuestionListOut(
            items=[
                QuestionOut(
                    id=question.id,
                    product_id=question.product_id,
                    user_id=question.user_id,
                    body=question.body,
                    created_at=question.created_at,
                    answers=grouped.get(question.id, []),
                )
                for question in page
            ],
            next_cursor=next_cursor,
        )

    async def answer_question(
        self, user_id: uuid.UUID, question_id: uuid.UUID, body: str
    ) -> AnswerOut:
        """Responde una pregunta (solo el vendedor dueño de la tienda del producto)."""
        question = await self._questions.get_question(question_id)
        if question is None:
            raise AppError(404, "question_not_found", "Question not found.")

        product = await self._product(question.product_id)
        store_id = await self._store_id_for(user_id)
        if product.store_id != store_id:
            raise AppError(403, "not_store_owner", "Only the seller of this product can answer.")

        answer = await self._questions.add_answer(
            Answer(question_id=question.id, store_id=store_id, user_id=user_id, body=body)
        )
        await self._session.commit()
        return _answer_out(answer)

    # ---------- Internos ----------

    async def _product(self, product_id: uuid.UUID) -> Product:
        result = await self._session.execute(
            select(Product).where(Product.id == product_id, Product.deleted_at.is_(None))
        )
        product = result.scalar_one_or_none()
        if product is None:
            raise AppError(404, "product_not_found", "Product not found.")
        return product

    async def _owned_review(self, user_id: uuid.UUID, review_id: uuid.UUID) -> Review:
        review = await self._reviews.get_by_id(review_id)
        if review is None or review.user_id != user_id:
            raise AppError(404, "review_not_found", "Review not found.")
        return review

    async def _store_id_for(self, user_id: uuid.UUID) -> uuid.UUID:
        result = await self._session.execute(
            select(Store.id).where(Store.user_id == user_id, Store.deleted_at.is_(None))
        )
        store_id = result.scalar_one_or_none()
        if store_id is None:
            raise AppError(403, "store_required", "You need a store to answer questions.")
        return store_id

    async def _refresh_reputation(self, product_id: uuid.UUID, store_id: uuid.UUID) -> None:
        """Recalcula los agregados de reputación del producto y de la tienda."""
        await self._reviews.recompute_product(product_id)
        await self._reviews.recompute_store(store_id)
