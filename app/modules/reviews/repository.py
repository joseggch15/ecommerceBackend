"""Repositorios del módulo de reseñas."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import Product
from app.modules.orders.models import Order, OrderItem, SellerOrder, SellerOrderStatus
from app.modules.reviews.models import Answer, Question, Review
from app.modules.sellers.models import Store


class ReviewRepository:
    """Acceso a reseñas y a los agregados de reputación."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, review: Review) -> Review:
        self._session.add(review)
        await self._session.flush()
        return review

    async def get_by_id(self, review_id: uuid.UUID) -> Review | None:
        result = await self._session.execute(select(Review).where(Review.id == review_id))
        return result.scalar_one_or_none()

    async def get_by_user_product(self, user_id: uuid.UUID, product_id: uuid.UUID) -> Review | None:
        result = await self._session.execute(
            select(Review).where(Review.user_id == user_id, Review.product_id == product_id)
        )
        return result.scalar_one_or_none()

    async def list_by_product(
        self, product_id: uuid.UUID, *, limit: int, cursor: tuple[datetime, uuid.UUID] | None
    ) -> list[Review]:
        stmt = (
            select(Review)
            .where(Review.product_id == product_id, Review.is_published.is_(True))
            .order_by(Review.created_at.desc(), Review.id.desc())
            .limit(limit)
        )
        if cursor is not None:
            created_at, review_id = cursor
            stmt = stmt.where(
                or_(
                    Review.created_at < created_at,
                    (Review.created_at == created_at) & (Review.id < review_id),
                )
            )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def delete(self, review: Review) -> None:
        await self._session.delete(review)

    async def stats_for_product(self, product_id: uuid.UUID) -> tuple[Decimal | None, int]:
        average, count = (
            await self._session.execute(
                select(func.avg(Review.rating), func.count(Review.id)).where(
                    Review.product_id == product_id, Review.is_published.is_(True)
                )
            )
        ).one()
        rounded = Decimal(str(average)).quantize(Decimal("0.01")) if average is not None else None
        return rounded, int(count)

    async def recompute_product(self, product_id: uuid.UUID) -> None:
        """Recalcula los agregados del producto en su propio objeto ORM.

        No se usa `update()` masivo: expira instancias de la sesión y, en async,
        provoca `MissingGreenlet` al leerlas después.
        """
        average, count = await self.stats_for_product(product_id)
        product = (
            await self._session.execute(select(Product).where(Product.id == product_id))
        ).scalar_one_or_none()
        if product is not None:
            product.rating_average = average
            product.rating_count = count

    async def recompute_store(self, store_id: uuid.UUID) -> None:
        average, count = (
            await self._session.execute(
                select(func.avg(Review.rating), func.count(Review.id)).where(
                    Review.store_id == store_id, Review.is_published.is_(True)
                )
            )
        ).one()
        rounded = Decimal(str(average)).quantize(Decimal("0.01")) if average is not None else None
        store = (
            await self._session.execute(select(Store).where(Store.id == store_id))
        ).scalar_one_or_none()
        if store is not None:
            store.rating_average = rounded
            store.rating_count = int(count)

    async def delivered_order_item_id(
        self, user_id: uuid.UUID, product_id: uuid.UUID
    ) -> uuid.UUID | None:
        """Id de la línea de orden entregada (prueba de compra verificada)."""
        result = await self._session.execute(
            select(OrderItem.id)
            .join(SellerOrder, SellerOrder.id == OrderItem.seller_order_id)
            .join(Order, Order.id == SellerOrder.order_id)
            .where(
                Order.user_id == user_id,
                OrderItem.product_id == product_id,
                SellerOrder.status == SellerOrderStatus.DELIVERED,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()


class QuestionRepository:
    """Acceso a preguntas y respuestas."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, question: Question) -> Question:
        self._session.add(question)
        await self._session.flush()
        return question

    async def get_question(self, question_id: uuid.UUID) -> Question | None:
        result = await self._session.execute(
            select(Question).where(Question.id == question_id, Question.is_published.is_(True))
        )
        return result.scalar_one_or_none()

    async def list_by_product(
        self,
        product_id: uuid.UUID,
        *,
        limit: int,
        cursor: tuple[datetime, uuid.UUID] | None,
    ) -> list[Question]:
        stmt = (
            select(Question)
            .where(Question.product_id == product_id, Question.is_published.is_(True))
            .order_by(Question.created_at.desc(), Question.id.desc())
            .limit(limit)
        )
        if cursor is not None:
            created_at, question_id = cursor
            stmt = stmt.where(
                or_(
                    Question.created_at < created_at,
                    (Question.created_at == created_at) & (Question.id < question_id),
                )
            )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def add_answer(self, answer: Answer) -> Answer:
        self._session.add(answer)
        await self._session.flush()
        return answer

    async def list_answers(self, question_ids: list[uuid.UUID]) -> list[Answer]:
        if not question_ids:
            return []
        result = await self._session.execute(
            select(Answer).where(Answer.question_id.in_(question_ids)).order_by(Answer.created_at)
        )
        return list(result.scalars().all())
