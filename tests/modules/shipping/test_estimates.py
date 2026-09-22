"""Pruebas de la estimación de entrega (función pura, sin base de datos).

Lo que se protege: que las fechas caigan en días hábiles, que el envío internacional sea más
lento que el local y que la respuesta **declare que es una estimación configurable**
(`source`), para que la interfaz nunca la presente como una promesa de transportadora.
"""

import uuid
from datetime import date
from decimal import Decimal

from app.modules.shipping.estimates import add_business_days, delivery_window, estimate_shipping


def test_add_business_days_skips_weekends() -> None:
    start = date(2026, 9, 18)

    for days in (1, 2, 5, 10):
        result = add_business_days(start, days)
        assert result > start
        assert result.weekday() < 5, "una fecha estimada no puede caer en fin de semana"

    # Cinco días hábiles después siempre es el mismo día de la semana (una semana laboral completa).
    assert add_business_days(start, 5).weekday() == start.weekday()


def test_add_business_days_with_zero_or_negative_does_not_move() -> None:
    start = date(2026, 9, 18)
    assert add_business_days(start, 0) == start
    assert add_business_days(start, -3) == start


def test_delivery_window_is_slower_for_international() -> None:
    local = delivery_window(country="CO")
    international = delivery_window(country="US")
    default = delivery_window(country=None)

    assert default == local, "sin país de destino se usa el país de origen"
    assert international.transit_days_min > local.transit_days_min
    assert international.transit_days_max > local.transit_days_max


def test_estimate_window_is_ordered_and_declares_its_source() -> None:
    estimate = estimate_shipping(
        product_id=uuid.uuid4(),
        store_id=uuid.uuid4(),
        country="CO",
        today=date(2026, 9, 18),
    )

    assert estimate.source == "configured_default"
    assert estimate.destination_country == "CO"
    assert estimate.shipping_cost == Decimal("0")
    assert estimate.free_shipping is True
    assert estimate.estimated_delivery_min < estimate.estimated_delivery_max
    assert estimate.estimated_delivery_min.weekday() < 5
    assert estimate.estimated_delivery_max.weekday() < 5
