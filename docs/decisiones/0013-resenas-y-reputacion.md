# Decisión 0013: Reseñas, preguntas y reputación (Fase 9)

**Fecha:** 2026-09-22
**Estado:** Aceptada

## Contexto

Un marketplace sin reputación no vende: el comprador necesita saber si el producto y el vendedor son confiables. A la vez, hay que evitar reseñas falsas y respuestas sin control.

## Decisiones

### 1. Solo reseña quien compró y recibió
- `reviews.order_item_id` apunta a la **línea de orden entregada** que da derecho a reseñar (`seller_orders.status = delivered`).
- Si no existe esa línea → **403** `purchase_required`. El campo `verified_purchase` se deriva de que haya `order_item_id`.
- También se enlaza `store_id` (para la reputación del vendedor) y `product_id`.

### 2. Una reseña por comprador y producto
- `UNIQUE(user_id, product_id)`. Un segundo intento → **409** `review_exists`.
- Para corregirla se **edita** (`PATCH /reviews/{id}`), y solo su autor puede hacerlo (si no, **404**, para no filtrar su existencia).

### 3. Reputación denormalizada
- `products.rating_average`/`rating_count` y `stores.rating_average`/`rating_count` (`NUMERIC(3,2)` e `Integer`) se **recalculan** en el servicio al crear, editar o borrar la reseña (agregado sobre reseñas publicadas).
- Se denormaliza para que el listado/búsqueda no haga `AVG` en cada consulta.
- ⚠️ **Implementación:** los agregados se escriben sobre el **objeto ORM** (un `select` + asignación), **no** con `update()` masivo de SQLAlchemy. El bulk-update expira instancias de la sesión y leerlas después en async lanza `MissingGreenlet` (I/O fuera del greenlet). Además se hace `refresh` antes de responder.

### 4. Preguntas y respuestas
- Cualquier usuario autenticado pregunta (`questions`); **solo el vendedor dueño de la tienda del producto** responde (`answers.store_id` debe coincidir). Si no tiene tienda → **403** `store_required`; si es de otra tienda → **403** `not_store_owner`.
- Al responder se guarda `store_id` y el `user_id` que respondió (trazabilidad).

### 5. Moderación preparada, pero no activa
- `is_published` en reseñas y preguntas: el servicio publica por defecto y el listado solo devuelve publicados. La herramienta de moderación (admin) llega en la Fase 12.
- Sin fotos en esta fase (queda para cuando haya almacenamiento de imágenes de reseñas).

## Consecuencias

- La nota del producto y de la tienda es verificable y auditable (se sabe qué compra la respalda).
- Editar o borrar recalcula la reputación; borrar no deja el promedio “sucio”.
- Preguntas y respuestas quedan asociadas a la tienda que responde, listas para mostrarse en la ficha del producto.
