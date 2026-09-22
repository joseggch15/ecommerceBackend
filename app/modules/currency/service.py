"""Lógica de negocio del módulo de monedas (tasas con caché en Redis y conversión)."""

import json
from decimal import ROUND_HALF_UP, Decimal

from redis.asyncio import Redis

from app.core.config import settings
from app.core.errors import AppError
from app.modules.currency.currencies import (
    CURRENCY_NAMES,
    currency_symbol,
    is_supported_currency,
)
from app.modules.currency.provider import ExchangeRateProvider, default_provider
from app.modules.currency.schemas import ConvertOut, CurrencyOut, RatesOut


class CurrencyService:
    """Tasas de cambio (cacheadas en Redis) y conversión informativa."""

    def __init__(self, redis: Redis, provider: ExchangeRateProvider | None = None) -> None:
        self._redis = redis
        self._provider = provider or default_provider

    def list_currencies(self) -> list[CurrencyOut]:
        """Devuelve todas las monedas ISO 4217 soportadas."""
        return [
            CurrencyOut(code=code, name=name, symbol=currency_symbol(code))
            for code, name in sorted(CURRENCY_NAMES.items())
        ]

    async def get_rates(self, base: str, *, force_refresh: bool = False) -> RatesOut:
        code = base.upper()
        self._ensure_supported(code)
        rates = await self._rates_for(code, force_refresh=force_refresh)
        return RatesOut(base=code, rates=rates)

    async def convert(self, amount: Decimal, from_currency: str, to_currency: str) -> ConvertOut:
        source = from_currency.upper()
        target = to_currency.upper()
        self._ensure_supported(source)
        self._ensure_supported(target)

        if source == target:
            return ConvertOut(
                amount=amount,
                from_currency=source,
                to_currency=target,
                rate=Decimal("1"),
                converted_amount=amount,
            )

        rates = await self._rates_for(source)
        rate = rates.get(target)
        if rate is None:
            raise AppError(
                status_code=400,
                code="unsupported_currency",
                detail=f"There is no exchange rate for {target}.",
            )

        converted = (amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return ConvertOut(
            amount=amount,
            from_currency=source,
            to_currency=target,
            rate=rate,
            converted_amount=converted,
        )

    async def _rates_for(self, base: str, *, force_refresh: bool = False) -> dict[str, Decimal]:
        cache_key = f"exchange_rates:{base}"
        if not force_refresh:
            cached = await self._redis.get(cache_key)
            if cached is not None:
                data = json.loads(cached)
                if isinstance(data, dict) and data:
                    return {str(code): Decimal(str(value)) for code, value in data.items()}

        rates = await self._provider.get_rates(base)
        rates[base] = Decimal("1")
        payload = json.dumps({code: str(value) for code, value in rates.items()})
        await self._redis.set(cache_key, payload, ex=settings.EXCHANGE_RATE_CACHE_TTL_SECONDS)
        return rates

    @staticmethod
    def _ensure_supported(code: str) -> None:
        if not is_supported_currency(code):
            raise AppError(
                status_code=400,
                code="unsupported_currency",
                detail=f"Unsupported currency: {code}.",
            )
