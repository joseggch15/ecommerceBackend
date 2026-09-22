"""Schemas Pydantic del módulo de monedas."""

from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class CurrencyOut(BaseModel):
    code: str
    name: str
    symbol: str


class RatesOut(BaseModel):
    base: str
    rates: dict[str, Decimal]


class ConvertRequest(BaseModel):
    amount: Decimal = Field(ge=0)
    from_currency: str = Field(min_length=3, max_length=3)
    to_currency: str = Field(min_length=3, max_length=3)

    @field_validator("from_currency", "to_currency")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.upper()


class ConvertOut(BaseModel):
    amount: Decimal
    from_currency: str
    to_currency: str
    rate: Decimal
    converted_amount: Decimal


class LocaleOut(BaseModel):
    country: str | None
    currency: str
    language: str
    timezone: str
