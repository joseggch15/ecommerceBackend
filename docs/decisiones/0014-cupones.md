# Decisión 0014: Promociones y cupones (Fase 10)

**Fecha:** 2026-09-22
**Estado:** Aceptada

## Contexto

Hacen falta descuentos controlados: un cupón que el comprador escribe en el checkout, con límites (vigencia, mínimo de compra, usos totales y por usuario) y sin que se pueda reutilizar la misma orden.

## Decisiones

### 1. `coupons` + `coupon_redemptions`
- **`coupons`**: `code` único (se normaliza a mayúsculas), `discount_type` (`percent`/`fixed`), `value`, `currency`, `min_purchase`, `starts_at`/`ends_at`, `max_uses`, `max_uses_per_user`, `used_count`, `store_id` opcional e `is_active`.
- **`coupon_redemptions`**: `coupon_id`, `user_id`, `order_id`, `amount` con `UNIQUE(coupon_id, order_id)` → aplicar dos veces la misma orden es imposible, incluso con reintentos.

### 2. Aplicación dentro de la transacción del checkout
- `POST /orders` acepta `coupon_code`; se valida **antes** de crear nada y el descuento se calcula sobre el subtotal del carrito.
- El descuento se **prorratea por vendedor** (`prorate`, proporcional al subtotal de cada tienda y sin perder centavos: el residuo va a la última) y queda en `seller_orders.discount_amount`.
- La **comisión se calcula sobre el neto** (`line_total − line_discount`), para no cobrar comisión de dinero que no se cobró; `payout_amount = subtotal − discount_amount − commission_amount`.
- `orders.discount_total` y `orders.total = subtotal + shipping − discount`.
- El canje y el incremento de `used_count` ocurren en la **misma transacción**; si algo falla (p. ej. stock), se revierte todo el cupón también.

### 3. Vista previa separada del consumo
- `POST /coupons/validate` (autenticado) calcula el descuento sobre el **carrito actual** y **no** consume el cupón. Permite al frontend mostrar “−2.500” antes de pagar.
- El endpoint es de solo lectura: no registra canjes.

### 4. Reglas y errores explícitos
- Inactivo o inexistente → **404** `coupon_not_found`. Fuera de vigencia → **409** `coupon_not_started`/`coupon_expired`. Bajo el mínimo → **409** `min_purchase_not_met`. Límites → **409** `coupon_usage_limit`/`coupon_user_limit`. Código repetido → **409** `coupon_exists`.
- Un cupón `percent` no puede pasar de 100 (**400** `invalid_coupon_value`).
- El descuento nunca supera el subtotal (un cupón fijo mayor que la compra deja el total en 0, nunca en negativo).

### 5. Administración solo para admin
- Crear/listar/desactivar exige rol `admin` (`require_roles(UserRole.ADMIN)`). No se borran cupones: se **desactivan** (`is_active = False`) para no perder el histórico de canjes.

## Consecuencias

- El descuento es auditable por vendedor y por orden, y la comisión nunca se calcula sobre dinero descontado.
- Los límites se cumplen incluso con reintentos del cliente (idempotencia por orden + contadores).
- Queda pendiente el filtrado real por tienda/producto/categoría de las líneas y los descuentos automáticos por campaña.
