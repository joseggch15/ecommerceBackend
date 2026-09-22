"""Schemas Pydantic del módulo de pagos."""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class SandboxOutcome(enum.StrEnum):
    """Desenlaces que puede simular la pasarela sandbox."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"


class PaymentOut(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    provider: str
    provider_reference: str
    status: str
    amount: Decimal
    currency: str
    checkout_url: str | None
    failure_reason: str | None
    paid_at: datetime | None
    created_at: datetime


class WebhookAckOut(BaseModel):
    """Acuse de recibo del webhook (siempre 200 para que el proveedor no reintente)."""

    received: bool
    duplicate: bool = False
