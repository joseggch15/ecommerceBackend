"""Estimación de entrega de un producto.

**Por qué existe este módulo.** Hoy no hay tarifas por zona ni transportadora integrada (ver
la decisión 0012: el envío del comprador se define en el checkout y hoy es 0), así que el
backend no puede pedirle una fecha a nadie. Lo que sí puede hacer —y hace— es dar una
**estimación determinista y configurable**: días de preparación + días de tránsito, contando
días hábiles y sin contar el día de hoy. La respuesta lo declara en su campo `source`
(`configured_default`), para que quede claro que **no** viene de una transportadora y el
frontend pueda enseñarla como aproximada, nunca como una promesa.

Cuando existan tarifas reales o una integración con transportadora, solo cambia la función
`estimate_shipping()`: el contrato `ShippingEstimateOut` se mantiene igual.
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from pydantic import BaseModel

from app.core.config import settings


@dataclass(frozen=True)
class DeliveryWindow:
    """Días de preparación y de tránsito de un envío."""

    handling_days: int
    transit_days_min: int
    transit_days_max: int


class ShippingEstimateOut(BaseModel):
    """Estimación de entrega de un producto (fechas ISO y coste en la moneda del vendedor)."""

    product_id: uuid.UUID
    store_id: uuid.UUID
    destination_country: str
    handling_days: int
    transit_days_min: int
    transit_days_max: int
    estimated_delivery_min: date
    estimated_delivery_max: date
    shipping_cost: Decimal
    free_shipping: bool
    source: str


def add_business_days(start: date, days: int) -> date:
    """Suma días hábiles (sin sábados ni domingos) a una fecha."""
    current = start
    remaining = max(days, 0)

    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1

    return current


def delivery_window(*, country: str | None, origin_country: str | None = None) -> DeliveryWindow:
    """Días de preparación y tránsito según el país de destino (valores configurables)."""
    origin = (origin_country or settings.SHIPPING_ORIGIN_COUNTRY).strip().upper()
    destination = (country or origin).strip().upper()

    if destination == origin:
        return DeliveryWindow(
            handling_days=settings.SHIPPING_HANDLING_DAYS,
            transit_days_min=settings.SHIPPING_TRANSIT_DAYS_MIN,
            transit_days_max=settings.SHIPPING_TRANSIT_DAYS_MAX,
        )

    return DeliveryWindow(
        handling_days=settings.SHIPPING_HANDLING_DAYS,
        transit_days_min=settings.SHIPPING_INTERNATIONAL_TRANSIT_DAYS_MIN,
        transit_days_max=settings.SHIPPING_INTERNATIONAL_TRANSIT_DAYS_MAX,
    )


def estimate_shipping(
    *,
    product_id: uuid.UUID,
    store_id: uuid.UUID,
    country: str | None = None,
    today: date | None = None,
) -> ShippingEstimateOut:
    """Construye la estimación de entrega.

    Es una función pura: la fecha de hoy se puede inyectar en las pruebas.
    """
    start = today or date.today()
    window = delivery_window(country=country)

    return ShippingEstimateOut(
        product_id=product_id,
        store_id=store_id,
        destination_country=(country or settings.SHIPPING_ORIGIN_COUNTRY).strip().upper(),
        handling_days=window.handling_days,
        transit_days_min=window.transit_days_min,
        transit_days_max=window.transit_days_max,
        estimated_delivery_min=add_business_days(
            start, window.handling_days + window.transit_days_min
        ),
        estimated_delivery_max=add_business_days(
            start, window.handling_days + window.transit_days_max
        ),
        shipping_cost=Decimal("0"),
        free_shipping=settings.SHIPPING_FREE,
        source="configured_default",
    )
