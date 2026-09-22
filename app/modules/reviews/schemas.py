"""Schemas Pydantic del módulo de reseñas, preguntas y respuestas."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ReviewCreate(BaseModel):
    product_id: uuid.UUID
    rating: int = Field(ge=1, le=5)
    title: str | None = Field(default=None, max_length=150)
    body: str | None = Field(default=None, max_length=2000)


class ReviewUpdate(BaseModel):
    rating: int | None = Field(default=None, ge=1, le=5)
    title: str | None = Field(default=None, max_length=150)
    body: str | None = Field(default=None, max_length=2000)


class ReviewOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    user_id: uuid.UUID
    store_id: uuid.UUID
    rating: int
    title: str | None
    body: str | None
    verified_purchase: bool
    created_at: datetime
    updated_at: datetime


class ReviewListOut(BaseModel):
    items: list[ReviewOut]
    next_cursor: str | None
    rating_average: Decimal | None
    rating_count: int


class QuestionCreate(BaseModel):
    body: str = Field(min_length=3, max_length=2000)


class AnswerCreate(BaseModel):
    body: str = Field(min_length=2, max_length=2000)


class AnswerOut(BaseModel):
    id: uuid.UUID
    store_id: uuid.UUID
    body: str
    created_at: datetime


class QuestionOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    user_id: uuid.UUID
    body: str
    created_at: datetime
    answers: list[AnswerOut]


class QuestionListOut(BaseModel):
    items: list[QuestionOut]
    next_cursor: str | None
