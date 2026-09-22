"""Pruebas del módulo de monedas (tasas, conversión y localización)."""

from decimal import Decimal

from httpx import AsyncClient
from redis.asyncio import Redis

from app.main import app
from app.modules.currency.api import get_currency_service
from app.modules.currency.provider import ExchangeRateProvider
from app.modules.currency.service import CurrencyService

TEST_REDIS_URL = "redis://localhost:6379/1"


class FakeExchangeRateProvider(ExchangeRateProvider):
    """Proveedor de prueba: 1 COP = 0.00025 USD."""

    async def get_rates(self, base: str) -> dict[str, Decimal]:
        return {"USD": Decimal("0.00025"), "EUR": Decimal("0.00023")}


def _override_service(redis: Redis) -> None:
    app.dependency_overrides[get_currency_service] = lambda: CurrencyService(
        redis, FakeExchangeRateProvider()
    )


async def test_list_currencies(integration_client: AsyncClient) -> None:
    resp = await integration_client.get("/api/v1/currencies")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) > 100
    codes = {item["code"] for item in body}
    assert {"COP", "USD", "EUR"} <= codes


async def test_get_rates(integration_client: AsyncClient) -> None:
    redis: Redis = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    _override_service(redis)
    try:
        resp = await integration_client.get("/api/v1/currencies/rates", params={"base": "COP"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["base"] == "COP"
        assert Decimal(str(body["rates"]["USD"])) == Decimal("0.00025")
    finally:
        await redis.aclose()


async def test_convert_currency(integration_client: AsyncClient) -> None:
    redis: Redis = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    _override_service(redis)
    try:
        resp = await integration_client.post(
            "/api/v1/currencies/convert",
            json={"amount": "10000", "from_currency": "cop", "to_currency": "usd"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["from_currency"] == "COP"
        assert body["to_currency"] == "USD"
        # 10000 * 0.00025 = 2.50
        assert Decimal(str(body["converted_amount"])) == Decimal("2.50")
    finally:
        await redis.aclose()


async def test_convert_same_currency(integration_client: AsyncClient) -> None:
    redis: Redis = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    _override_service(redis)
    try:
        resp = await integration_client.post(
            "/api/v1/currencies/convert",
            json={"amount": "5000", "from_currency": "COP", "to_currency": "COP"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert Decimal(str(body["rate"])) == Decimal("1")
        assert Decimal(str(body["converted_amount"])) == Decimal("5000")
    finally:
        await redis.aclose()


async def test_unsupported_currency(integration_client: AsyncClient) -> None:
    redis: Redis = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    _override_service(redis)
    try:
        resp = await integration_client.post(
            "/api/v1/currencies/convert",
            json={"amount": "1000", "from_currency": "COP", "to_currency": "XXX"},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "unsupported_currency"
    finally:
        await redis.aclose()


async def test_locale_by_country(integration_client: AsyncClient) -> None:
    resp = await integration_client.get(
        "/api/v1/currencies/locale",
        headers={"X-Country": "US", "Accept-Language": "en-US,en;q=0.9"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["country"] == "US"
    assert body["currency"] == "USD"
    assert body["language"] == "en-US"
    assert body["timezone"] == "America/New_York"


async def test_locale_default(integration_client: AsyncClient) -> None:
    resp = await integration_client.get("/api/v1/currencies/locale")
    assert resp.status_code == 200
    body = resp.json()
    assert body["country"] is None
    assert body["currency"] == "COP"
    assert body["language"] == "es"
    assert body["timezone"] == "America/Bogota"
