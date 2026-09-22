# Decisión 0012: Envíos (Fase 8)

**Fecha:** 2026-09-22
**Estado:** Aceptada

## Contexto

Un pedido puede tener productos de varios vendedores: cada uno despacha desde su bodega, con su transportadora y su guía. El comprador debe poder seguir cada envío por separado.

## Decisiones

### 1. `shipments` por sub-orden (no por orden)
- Un envío por `seller_order` (`seller_order_id` **ÚNICO**): una guía por vendedor.
- `shipment_events` guarda la **línea de tiempo** (estado, descripción, fecha), para mostrar el seguimiento sin depender de la transportadora.
- Se rechaza crear un segundo envío para la misma venta (**409** `shipment_exists`); para corregir datos se usa `PATCH`.

### 2. Estados y sincronización con la orden
- `pending → ready → shipped → in_transit → delivered`, y `returned` desde `shipped`/`in_transit`/`delivered`; `cancelled` desde `pending`/`ready`. Transición inválida → **409** `invalid_status_transition`.
- El envío **mueve la sub-orden**: `shipped`/`in_transit` → `seller_orders.status = shipped` (pasando por `processing`, respetando la máquina de estados de la orden); `delivered` → `delivered`.
- Cuando **todas** las sub-órdenes están `delivered` y la orden estaba `paid`, la orden pasa a **`completed`**.
- `shipped_at`/`delivered_at` se sellan una sola vez (el primero en marcar la transición).

### 3. El `cost` del envío es logístico, no de cara al comprador
- `shipments.cost` = lo que el vendedor paga a la transportadora (información para sus finanzas).
- Lo que **paga el comprador** por envío se define en el checkout (`seller_orders.shipping_cost` / `orders.shipping_total`, hoy `0`). Separarlo evita reescribir el total de una orden ya pagada.
- Queda pendiente una tabla de tarifas por zona/tarifa del vendedor; se abordará cuando se necesite cobrar envío.

### 4. Autorización
- El vendedor solo ve y edita el envío de **sus** ventas (se comprueba que la sub-orden pertenece a su tienda; si no, **404** para no filtrar existencia). Sin tienda → **403** `store_required`.
- El comprador ve los envíos de **su** orden (`GET /orders/{id}/shipments`), y ahí no se expone el `cost`.

### 5. Nada de transportadoras reales todavía
- Igual que con los pagos, no hay integración con transportadoras: los datos (transportadora, guía, URL) los aporta el vendedor. Integrar una API logística (p. ej. webhooks de tracking) es trabajo de un módulo aparte.

## Consecuencias

- El comprador sigue cada paquete por separado y la orden se cierra sola al entregarse todo.
- El vendedor no necesita la API de la transportadora para operar (puede cargar la guía a mano).
- El costo logístico queda separado del dinero cobrado al comprador.

## Nota operativa (incidente)

El autogenerate de esta fase detectó "removed table" para casi todas las tablas porque `ruff check --fix` había borrado los imports de modelos de `migrations/env.py`. **La migración que se generó se descartó sin aplicar** (dropeaba todo). Ahora `env.py` referencia los módulos en `_MODEL_MODULES` y lanza `RuntimeError` si falta algún modelo en `Base.metadata`, así que el fallo no puede pasar desapercibido.
