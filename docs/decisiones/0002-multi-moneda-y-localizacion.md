# Decisión 0002: Multi-moneda y localización

**Fecha:** 2026-09-21
**Estado:** Aceptada

## Contexto

El marketplace opera en Colombia (moneda base **COP**), pero puede recibir compradores de cualquier país. El usuario pidió que la moneda, el idioma y la zona horaria se adapten a la ubicación del visitante, con posibilidad de cambiarlos manualmente (como Amazon).

## Decisión

1. **Detección automática por ubicación** (país del usuario) para definir moneda, idioma y zona horaria como valor inicial.
2. El **usuario puede cambiar** manualmente estas preferencias, que se guardan en su perfil (`preferred_currency`, `preferred_language`, `timezone`).
3. **Conversión de moneda** mediante una **API de tasas de cambio** (con caché en Redis para no llamar en cada petición).
4. **Regla de oro del dinero:** los precios se guardan y se cobran **siempre en la moneda del vendedor** (por defecto COP). La conversión a otras monedas es **informativa** (mostrar "≈ USD 25") para el comprador.
5. La **API responde en inglés** (estándar) con un `code` de error estable; el **frontend** traduce mensajes y adapta idioma/zona horaria. Internamente todo se guarda en **UTC**.

## Consecuencias

**Positivas:**
- Evita errores de redondeo y complejidad fiscal al cobrar siempre en la moneda del vendedor.
- Mejor experiencia para compradores internacionales (precios aproximados en su moneda).
- Frontera clara entre "precio real" (cobro) y "precio mostrado" (informativo).

**Negativas / a vigilar:**
- Dependencia de una API externa de tasas de cambio (mitigada con caché y con la conversión siendo solo informativa).
- El tipo de cambio mostrado puede diferir del de la pasarela si en el futuro se cobra en moneda local (se evaluaría como decisión aparte).

## Alternativas descartadas

- **Cobrar en la moneda local del comprador:** mayor fricción fiscal y de redondeo; se pospone.
- **Tasas de cambio manuales fijas:** requieren mantenimiento humano y quedan desactualizadas.
- **Moneda única COP sin conversión:** mala experiencia para compradores internacionales.

## Ubicación en la hoja de ruta

Se implementa como **Fase 4** (justo después de Inventario y búsqueda), porque desde la Fase 3 ya se muestran precios al comprador.
