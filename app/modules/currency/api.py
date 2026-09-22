"""Endpoints del módulo de monedas."""

from fastapi import APIRouter, Depends, Query, Request
from redis.asyncio import Redis

from app.core.locale import resolve_locale
from app.core.redis import get_redis
from app.modules.currency.schemas import (
    ConvertOut,
    ConvertRequest,
    CurrencyOut,
    LocaleOut,
    RatesOut,
)
from app.modules.currency.service import CurrencyService

router = APIRouter(tags=["currency"])


def get_currency_service(redis: Redis = Depends(get_redis)) -> CurrencyService:
    return CurrencyService(redis)


@router.get("/currencies", response_model=list[CurrencyOut])
async def list_currencies(
    service: CurrencyService = Depends(get_currency_service),
) -> list[CurrencyOut]:
    """Lista de monedas ISO 4217 soportadas."""
    return service.list_currencies()


@router.get("/currencies/rates", response_model=RatesOut)
async def get_rates(
    base: str = Query(default="COP", min_length=3, max_length=3),
    service: CurrencyService = Depends(get_currency_service),
) -> RatesOut:
    """Tasas de cambio con respecto a la moneda base (cacheadas)."""
    return await service.get_rates(base)


@router.post("/currencies/convert", response_model=ConvertOut)
async def convert(
    data: ConvertRequest,
    service: CurrencyService = Depends(get_currency_service),
) -> ConvertOut:
    """Convierte un monto entre monedas (información para el comprador)."""
    return await service.convert(data.amount, data.from_currency, data.to_currency)


@router.get("/currencies/locale", response_model=LocaleOut)
async def get_locale(request: Request) -> LocaleOut:
    """Devuelve la localización detectada para la petición."""
    locale = resolve_locale(request)
    return LocaleOut(
        country=locale.country,
        currency=locale.currency,
        language=locale.language,
        timezone=locale.timezone,
    )
