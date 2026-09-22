"""Proveedor de tasas de cambio (interfaz + implementación HTTP configurable)."""

from abc import ABC, abstractmethod
from decimal import Decimal, InvalidOperation

import httpx

from app.core.config import settings
from app.core.errors import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)


class ExchangeRateProvider(ABC):
    """Interfaz para obtener tasas de cambio (permite cambiar de proveedor)."""

    @abstractmethod
    async def get_rates(self, base: str) -> dict[str, Decimal]:
        """Devuelve las tasas tal que 1 unidad de `base` = X unidades de cada moneda."""


class HttpExchangeRateProvider(ExchangeRateProvider):
    """Proveedor HTTP configurable por variables de entorno.

    Por defecto usa una API pública que no requiere clave (para desarrollo).
    """

    async def get_rates(self, base: str) -> dict[str, Decimal]:
        url = f"{settings.EXCHANGE_RATE_API_URL.rstrip('/')}/{base.upper()}"
        params: dict[str, str] = {}
        if settings.EXCHANGE_RATE_API_KEY:
            params["access_key"] = settings.EXCHANGE_RATE_API_KEY

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            logger.warning("exchange_rate_fetch_failed", error=str(exc))
            raise AppError(
                status_code=503,
                code="exchange_rate_unavailable",
                detail="Exchange rates are not available right now.",
            ) from exc

        raw_rates = data.get("rates") if isinstance(data, dict) else None
        if not isinstance(raw_rates, dict):
            raise AppError(
                status_code=502,
                code="exchange_rate_invalid_response",
                detail="The exchange rate provider returned an invalid response.",
            )

        rates: dict[str, Decimal] = {}
        for code, value in raw_rates.items():
            try:
                rates[str(code).upper()] = Decimal(str(value))
            except InvalidOperation:
                continue

        if not rates:
            raise AppError(
                status_code=502,
                code="exchange_rate_invalid_response",
                detail="The exchange rate provider returned an invalid response.",
            )
        return rates


default_provider: ExchangeRateProvider = HttpExchangeRateProvider()
