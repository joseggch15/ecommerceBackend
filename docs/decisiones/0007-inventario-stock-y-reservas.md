# Decisión 0007: Inventario — stock y reservas (Fase 3b)

**Fecha:** 2026-09-22
**Estado:** Aceptada

## Contexto

El stock vivía en `product_variants.stock` (módulo catalog). En la Fase 3b se mueve al módulo `inventory`, que pasa a ser el dueño del stock, y se añaden reservas para que el checkout (Fase 6) no venda más de lo disponible.

## Decisiones

### 1. El stock vive en `inventory_items` (propiedad de inventory)
- `inventory_items`: `variant_id` (único), `quantity`, `reserved_quantity`. Disponible = `quantity - reserved_quantity`.
- Se **eliminó** `stock` de `product_variants` (frontera limpia: catalog no es dueño del stock).
- Al crear una variante, catalog registra el stock inicial llamando al **servicio público** `InventoryService.ensure_item()`.

### 2. Ledger de movimientos
- `inventory_movements` guarda cada cambio (delta + motivo): `initial`, `adjustment`, `reservation`, `release`. Sirve de auditoría.
- El `delta` representa el cambio en el stock **disponible**.

### 3. Reservas atómicas (cero sobreventa)
- `reserve()` lee el item con `SELECT ... FOR UPDATE` (bloqueo de fila), verifica disponible y suma a `reserved_quantity` dentro de la misma transacción. Dos compradores simultáneos no pueden reservar la última unidad dos veces.
- `release()` libera reservas (p. ej. si el pago no se completa).
- Si no hay stock suficiente → **409** con `code = "insufficient_stock"`.

### 4. Nota sobre migraciones con índices creados por SQL crudo
- `alembic autogenerate` **no ve** los índices creados con `op.execute(...)` (los de búsqueda) y generó un `DROP INDEX` incorrecto. Se revisó y corrigió la migración a mano: `autogenerate` siempre debe revisarse antes de aplicar.

## Consecuencias

- Inventario desacoplado del catálogo, con reservas seguras y auditables.
- El checkout (Fase 6) usará `reserve()`/`release()` para cobrar sin sobreventa.
