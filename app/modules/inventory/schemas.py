"""Schemas Pydantic del módulo de inventario."""

import uuid

from pydantic import BaseModel, ConfigDict, Field


class StockAdjustRequest(BaseModel):
    delta: int = Field(ge=-1_000_000, le=1_000_000)
    reason: str = Field(default="adjustment", min_length=1, max_length=50)


class ReserveRequest(BaseModel):
    quantity: int = Field(gt=0)


class InventoryItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    variant_id: uuid.UUID
    quantity: int
    reserved_quantity: int
    available: int
