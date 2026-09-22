"""Resolución de la localización (país, moneda, idioma y zona horaria) del request."""

from dataclasses import dataclass

from starlette.requests import Request

from app.core.config import settings

# País (ISO 3166-1 alpha-2) -> (moneda, idioma, zona horaria)
COUNTRY_DEFAULTS: dict[str, tuple[str, str, str]] = {
    "AR": ("ARS", "es", "America/Argentina/Buenos_Aires"),
    "BO": ("BOB", "es", "America/La_Paz"),
    "BR": ("BRL", "pt", "America/Sao_Paulo"),
    "CA": ("CAD", "en", "America/Toronto"),
    "CL": ("CLP", "es", "America/Santiago"),
    "CN": ("CNY", "zh", "Asia/Shanghai"),
    "CO": ("COP", "es", "America/Bogota"),
    "CR": ("CRC", "es", "America/Costa_Rica"),
    "DE": ("EUR", "de", "Europe/Berlin"),
    "DO": ("DOP", "es", "America/Santo_Domingo"),
    "EC": ("USD", "es", "America/Guayaquil"),
    "ES": ("EUR", "es", "Europe/Madrid"),
    "FR": ("EUR", "fr", "Europe/Paris"),
    "GB": ("GBP", "en", "Europe/London"),
    "GT": ("GTQ", "es", "America/Guatemala"),
    "HN": ("HNL", "es", "America/Tegucigalpa"),
    "IN": ("INR", "en", "Asia/Kolkata"),
    "IT": ("EUR", "it", "Europe/Rome"),
    "JP": ("JPY", "ja", "Asia/Tokyo"),
    "MX": ("MXN", "es", "America/Mexico_City"),
    "NI": ("NIO", "es", "America/Managua"),
    "PA": ("PAB", "es", "America/Panama"),
    "PE": ("PEN", "es", "America/Lima"),
    "PR": ("USD", "es", "America/Puerto_Rico"),
    "PT": ("EUR", "pt", "Europe/Lisbon"),
    "PY": ("PYG", "es", "America/Asuncion"),
    "SV": ("USD", "es", "America/El_Salvador"),
    "US": ("USD", "en", "America/New_York"),
    "UY": ("UYU", "es", "America/Montevideo"),
    "VE": ("VES", "es", "America/Caracas"),
}


@dataclass(frozen=True)
class Locale:
    """Localización detectada para una petición."""

    country: str | None
    currency: str
    language: str
    timezone: str


def _parse_language(accept_language: str) -> str | None:
    """Extrae el idioma principal del header Accept-Language (p. ej. 'en-US' -> 'en')."""
    if not accept_language:
        return None
    first = accept_language.split(",")[0].strip()
    if not first:
        return None
    code = first.split(";")[0].strip()
    return code[:10] or None


def resolve_locale(request: Request) -> Locale:
    """Detecta la localización a partir de los headers del request.

    - `X-Country`: país del usuario (lo envía el frontend según su geolocalización).
    - `Accept-Language`: idioma preferido del navegador.
    """
    country_raw = request.headers.get("X-Country", "").strip().upper()
    country = country_raw or None
    language = _parse_language(request.headers.get("Accept-Language", ""))

    if country is not None and country in COUNTRY_DEFAULTS:
        currency, default_language, timezone = COUNTRY_DEFAULTS[country]
        return Locale(
            country=country,
            currency=currency,
            language=language or default_language,
            timezone=timezone,
        )

    return Locale(
        country=country,
        currency=settings.DEFAULT_CURRENCY,
        language=language or settings.DEFAULT_LANGUAGE,
        timezone=settings.DEFAULT_TIMEZONE,
    )
