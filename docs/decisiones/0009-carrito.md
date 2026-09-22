# Decisión 0009: Carrito (Fase 5)

**Fecha:** 2026-09-22
**Estado:** Aceptada

## Contexto

El comprador debe poder armar su carrito antes de pagar: como invitado (sin cuenta) y, si se registra, conservarlo entre dispositivos. Un mismo carrito puede tener productos de **varios vendedores** (el pago se dividirá por vendedor en la Fase 7).

## Decisiones

### 1. Dos almacenes según el tipo de comprador
- **Usuario registrado:** carrito **persistente** en PostgreSQL (`carts` 1:1 con `users`, `cart_items` con `UNIQUE(cart_id, variant_id)`).
- **Invitado:** carrito **temporal** en Redis (hash `guest_cart:{token}`) con **TTL de 7 días**, como indica el stack para datos efímeros.
- Motivo: los invitados generan volumen alto y desechable (no conviene ensuciar la BD), y perder un carrito de invitado es aceptable.

### 2. Identificación del invitado con `X-Cart-Token`
- El invitado envía el header `X-Cart-Token`; si no lo trae, la API genera uno y lo **devuelve en el mismo header de la respuesta** para que el frontend lo guarde (cookie/localStorage).
- Si hay `Authorization` válido, manda el carrito del usuario y el token se ignora (pero se acepta para poder fusionar).

### 3. Fusión explícita al iniciar sesión: `POST /cart/merge`
- Endpoint autenticado que suma las cantidades del carrito de invitado al del usuario (topando en `MAX_QUANTITY`) y **vacía** el temporal.
- Es explícito (no automático) para que el frontend lo llame tras el login y podamos informar cuántos ítems se fusionaron.

### 4. La línea se identifica por `variant_id`
- Se opera con `variant_id` (`PATCH/DELETE /cart/items/{variant_id}`) en vez de un id de línea, para que la misma URL sirva a invitados (Redis) y usuarios (BD) y sea idempotente.

### 5. El carrito no reserva stock
- El stock se reserva al crear la orden (Fase 6/7). El carrito solo **valida** que la variante exista; la disponibilidad se comprueba en el checkout. Evita reservas fantasma por carritos abandonados.

### 6. Cantidad máxima y totales
- `MAX_QUANTITY = 100` por variante.
- Los totales se calculan en el servidor con **`Decimal`** (nunca se confía en montos del cliente). La moneda es la de la plataforma (`DEFAULT_CURRENCY`); con precios multimoneda por vendedor habrá que agrupar por moneda (pendiente).

## Consecuencias

- El carrito de invitado no necesita usuario ni escrituras en BD.
- Al fusionar, el cliente puede ofrecer al invitado registrarse sin perder su selección.
- Limpieza automática de carritos de invitado por el TTL de Redis.
