# Decisión 0005: Productos, variantes e imágenes (Fase 2b)

**Fecha:** 2026-09-22
**Estado:** Aceptada

## Contexto

En la Fase 2b se construye el catálogo de productos: productos con variantes, SKU, precios, stock e imágenes.

## Decisiones

### 1. Producto → variantes (1:N) con valores de atributos EAV
- `products` (tienda + categoría + título/slug + descripción/marca + estado).
- `product_variants` (SKU único, precio, precio de comparación, stock).
- `variant_values` (variante ↔ atributo ↔ valor). Permite filtrar por facetas (Fase 3).

### 2. Estados de publicación con máquina de estados explícita
- `draft → active` (publish), `active → paused`, `paused → active`, `cualquiera → closed`.
- Las transiciones inválidas se rechazan con 409 (`invalid_product_status`).

### 3. Dinero: `NUMERIC` + `Decimal`, serializado como string con 2 decimales
- Precios con `Numeric(12, 2)` en BD y `Decimal` en Python (nunca float).
- Pydantic v2 serializa `Decimal` a string (ej. `"25000.00"`) preservando la escala. Las pruebas comparan montos con `Decimal(str(...))` para ser robustas.

### 4. Imágenes con MinIO + URLs prefirmadas
- MinIO (S3-compatible) en Docker (puertos 9000/9001), imagen `quay.io/minio/minio`.
- `boto3` para generar URLs prefirmadas (PUT) y crear el bucket (`ensure_bucket` en el arranque).
- Flujo: el cliente pide `POST /catalog/images/upload-url` → sube directo a MinIO → adjunta la imagen al producto con el `object_key`.

### 5. Autorización del vendedor
- Dependencia `get_approved_store`: resuelve la tienda aprobada del usuario actual; sin tienda aprobada → 403.
- Un vendedor solo gestiona sus propios productos (`_get_owned` verifica `store_id`).

## Consecuencias

- Catálogo completo listo para búsqueda (Fase 3) e inventario (Fase 3).
- Imágenes desacopladas de la app (subida directa al storage), más escalable.
- Precios con precisión decimal y serialización consistente en toda la API.
