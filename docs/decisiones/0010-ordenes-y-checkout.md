# Decisión 0010: Órdenes y checkout (Fase 6)

**Fecha:** 2026-09-22
**Estado:** Aceptada

## Contexto

El comprador paga **una sola vez**, pero su carrito puede tener productos de varias tiendas. Cada vendedor debe ver solo su parte, con su comisión y su monto a liquidar, y cada envío se gestionará por separado (Fase 8).

## Decisiones

### 1. `orders` + `seller_orders` + `order_items`
- **`orders`**: la compra del comprador. **Un solo pago** por toda la orden (`payment_status` vive aquí).
- **`seller_orders`**: una sub-orden por tienda (`UNIQUE(order_id, store_id)`) con su **estado de preparación/envío/entrega**, subtotal, costo de envío, comisión y `payout_amount` (lo que se liquida al vendedor).
- **`order_items`**: cuelgan de la sub-orden, con **snapshot** de título, etiqueta de variante, SKU, precio unitario, moneda, tasa de comisión y monto de comisión.
- Las FKs a `product_variants`/`products` son `ON DELETE SET NULL`: la orden sobrevive al borrado del producto (el snapshot es la verdad histórica).

### 2. Checkout en una sola transacción
`POST /orders` lee el carrito y, sin confirmar nada, reserva stock (`inventory.reserve(..., commit=False)`), arma la orden y vacía el carrito; **un único `commit` al final**. Si el stock no alcanza responde **409** y hace rollback: ni orden, ni reserva, ni carrito vaciado.
- La reserva usa `SELECT ... FOR UPDATE`, así que dos checkouts simultáneos no sobrevenden.
- `InventoryService.reserve/release` ganaron el parámetro `commit=False` para participar en transacciones mayores.

### 3. Idempotencia con `Idempotency-Key`
- El header se guarda en `orders.idempotency_key` con `UNIQUE(user_id, idempotency_key)`.
- Repetir el checkout con la misma clave devuelve **la misma orden** (no duplica ni vuelve a reservar stock).
- Se eligió la BD (no Redis) porque la garantía debe sobrevivir a reinicios.

### 4. Dinero y comisión
- Todo `NUMERIC` + `Decimal`, redondeo `HALF_UP` a 2 decimales.
- Comisión efectiva = `categories.commission_rate` si existe, si no `DEFAULT_COMMISSION_RATE`.
- `payout_amount` = `subtotal − commission_amount` (el costo de envío se resuelve en la Fase 8).

### 5. Máquina de estados
- Sub-orden: `pending → processing → shipped → delivered`, y `cancelled` desde `pending`/`processing`. Transición inválida → **409** `invalid_status_transition`.
- Orden: `pending → paid → completed`, más `cancelled`/`refunded`. Hoy solo `pending` es cancelable por el comprador (el pago llega en la Fase 7).

### 6. Sin tablas de pagos ni envíos
`payments` y `shipments` pertenecen a sus módulos (Fases 7 y 8). Aquí solo se dejan `orders.payment_status` y `seller_orders.status` como puntos de integración.

### 7. El carrito sigue sin reservar stock
Se mantiene la decisión 0009: la reserva ocurre en el checkout.

## Consecuencias

- Cada vendedor gestiona su sub-orden sin ver las de los demás; el comprador ve una sola compra.
- La comisión queda auditada por línea: si cambia la tasa de la categoría, las órdenes viejas no se alteran.
- Cancelar libera stock; pagar (Fase 7) moverá `payment_status` y el estado de la orden.
