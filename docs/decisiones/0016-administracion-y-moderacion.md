# Decisión 0016: Administración y moderación (Fase 12)

**Fecha:** 2026-09-22
**Estado:** Aceptada

## Contexto

La plataforma ya crea tiendas, productos, órdenes, pagos, reseñas y cupones, pero nadie puede **corregir** lo que sale mal: un producto engañoso, un vendedor que incumple, una reseña con insultos. Y todo lo que haga un administrador debe poder auditarse.

## Decisiones

### 1. Libro de auditoría `admin_actions`
- Cada acción guarda: `admin_user_id`, `action` (p. ej. `product.suspend`), `target_type`, `target_id`, `reason` y `data` JSONB con el detalle (título, estado resultante, nota…).
- `action` es un **string con formato `recurso.accion`** en lugar de un enum: añadir un tipo de moderación no requiere migración.
- Índices por `admin_user_id`, `action` y `target_id` para responder “¿qué pasó con esto?” y “¿qué hizo este admin?”.

### 2. Moderar es cambiar el estado, no borrar
- **Producto**: `pause`/`active` del catálogo (`ProductStatus`). Un producto pausado deja de ofrecerse pero conserva su histórico y sus órdenes.
- **Tienda**: `suspended`/`approved` (`StoreStatus`); el vendedor sigue existiendo.
- **Reseña**: `is_published = False` (ocultar) / `True` (republicar). Se reutiliza el campo que dejamos previsto en la Fase 9.
- Nada se borra: la moderación es reversible y auditable.

### 3. Ocultar una reseña recalcula la reputación
- `moderate_review` llama a los mismos `recompute_product`/`recompute_store` del módulo de reseñas (los que escriben sobre el objeto ORM, no con `update()` masivo).
- Así la nota del producto y de la tienda reflejan **solo** lo publicado: ocultar una reseña de 5 estrellas baja el promedio de inmediato.

### 4. Tablero de métricas (`GET /admin/metrics`)
- Usuarios, tiendas (no borradas), productos **activos**, órdenes **agrupadas por estado**, **GMV** (`SUM(orders.total)` de órdenes con `payment_status = paid`), **comisión acumulada** (`SUM(seller_orders.commission_amount)` de esas órdenes) y **top 5 vendedores** por subtotal vendido.
- Se calcula con agregaciones SQL (no se traen filas a Python) y se redondea a 2 decimales con `Decimal`.
- La definición de GMV es explícita: **solo órdenes pagadas** (ni pendientes ni reembolsadas).

### 5. Autorización de todo el prefijo `/admin`
- `require_roles(UserRole.ADMIN)` en cada endpoint; sin token → **401**, con rol `customer` → **403**.
- El rol se guarda en `users` y se asigna con `app/scripts/promote_admin.py` (Fase 1), así que no hay endpoint para “ascenderse”.

### 6. Alcance de esta fase
- No hay panel web: son endpoints para el panel que se construya encima.
- No se incluye moderación de **preguntas** (mismo patrón que reseñas: `is_published`) ni la gestión de disputas/devoluciones; quedan anotadas.

## Consecuencias

- Cualquier acción de moderación es reversible y queda con motivo y autor.
- El negocio tiene un tablero mínimo de salud (GMV, comisión, estados, mejores vendedores) sin depender de herramientas externas.
- Ocultar contenido no corrompe la reputación: los agregados siempre se recalculan sobre lo publicado.
