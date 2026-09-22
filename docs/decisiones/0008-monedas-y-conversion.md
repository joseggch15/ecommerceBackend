# Decisión 0008: Monedas y conversión (Fase 4)

**Fecha:** 2026-09-22
**Estado:** Aceptada

## Contexto

El marketplace opera en Colombia (COP) pero recibe compradores de otros países. Se necesita mostrar precios en la moneda del usuario y permitir elegir moneda/idioma/zona horaria.

## Decisiones

### 1. El precio real vive en la moneda del vendedor; la conversión es informativa
- Los precios se guardan y se cobran en la moneda del vendedor (por defecto **COP**).
- La conversión a otras monedas es **solo para mostrar** ("≈ USD 25"). Evita errores de redondeo y problemas fiscales.

### 2. Proveedor de tasas abstracto (`ExchangeRateProvider`)
- Interfaz con implementación HTTP (`HttpExchangeRateProvider`) configurable por `.env` (`EXCHANGE_RATE_API_URL`, `EXCHANGE_RATE_API_KEY`).
- Por defecto usa una **API pública sin clave** (desarrollo). Cambiar de proveedor = cambiar variables de entorno, sin tocar código.
- Si la API falla → **503** `exchange_rate_unavailable` (no rompe la app).

### 3. Caché de tasas en Redis
- Las tasas se cachean por moneda base (`exchange_rates:{base}`) con **TTL** (`EXCHANGE_RATE_CACHE_TTL_SECONDS`, 1 hora).
- Se guardan como JSON con valores en **string** para no perder precisión al pasarlas a `Decimal`.

### 4. Localización por headers
- `X-Country` (lo envía el frontend según la geolocalización) + `Accept-Language`.
- Tabla de países → (moneda, idioma, zona horaria) con **valores por defecto** (`DEFAULT_CURRENCY`, `DEFAULT_LANGUAGE`, `DEFAULT_TIMEZONE`).
- El usuario puede **cambiar** sus preferencias manualmente (guardadas en `user_profiles`, Fase 1).

### 5. Todo con `Decimal`
- Las tasas y montos usan `Decimal` (se convierten desde string). El redondeo es a 2 decimales con `ROUND_HALF_UP`.

## Consecuencias

- Compradores internacionales ven precios en su moneda, sin comprometer la exactitud del cobro.
- El frontend traduce códigos de idioma/moneda; la API responde en inglés con `code`s estables.
