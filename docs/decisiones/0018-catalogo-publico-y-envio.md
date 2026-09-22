# 0018 · Catálogo público: stock y atributos en las variantes, tienda y estimación de envío

- **Fecha:** 22 de septiembre de 2026 (tarea de pendientes del frontend, bloqueantes de la F6)
- **Estado:** aceptada

## Contexto

El frontend necesitaba tres cosas para que la ficha de producto y el checkout funcionasen sin inventarse
datos (apartados 10 y 11 de `E:\ecommerce-web\docs/PENDIENTES-BACKEND.md`):

1. `VariantOut` solo traía `id`, `sku`, `price` y `compare_at_price`: ni stock, ni valores de atributo. El
   frontend tenía que pedir el stock **variante por variante** al endpoint de inventario (N peticiones por
   ficha) e identificar las presentaciones por su SKU («AUD-NEG») en lugar de por «Color: negro».
2. No existía ningún endpoint público de tienda: el nombre, el logo y la reputación solo los veía el propio
   vendedor (`/sellers/me`) o el admin (`/sellers`).
3. No había ninguna estimación de envío, y tampoco tarifas por zona ni transportadora integrada (decisión
   0012: el `shipping_cost` del comprador se define en el checkout y hoy es `0`).

Además, `new_object_key()` generaba claves como `products/<32 hex>png`, **sin el punto** antes de la extensión,
y el proxy de medios del frontend exige el punto en su lista blanca: todas las imágenes reales se rechazaban
(apartado 8).

## Decisión

1. **`VariantOut` trae `stock`, `available` y `attribute_values`** (`attribute_id`, `name`, `value`), y
   `ProductOut` trae `total_available`. Se resuelve en **dos consultas para todo el producto** (una para los
   niveles de inventario y otra para los valores de atributo), no variante por variante.
2. **`stock` y `available` no son lo mismo**: `stock` es `inventory_items.quantity` y `available` es
   `quantity - reserved_quantity`. La ficha enseña «quedan N» con `available`, que es lo que de verdad se puede
   vender; `total_available` suma los disponibles de todas las variantes.
3. **El inventario se consulta a través del módulo de inventario** (`InventoryService.availability_for`), que
   es quien sabe de reservas. Una variante **sin** fila de inventario se devuelve con 0 unidades en vez de
   omitirse: es más claro para quien pinta la interfaz.
4. **`GET /api/v1/stores/{store_id}` público, solo para tiendas aprobadas.** Devuelve nombre, slug,
   descripción, `logo_url`, `rating_average`, `rating_count`, `orders_delivered` (sub-órdenes en estado
   `delivered`) y `created_at`. Una tienda `pending`, `rejected` o `suspended` responde **404**, igual que una
   que no existe: el estado de la solicitud es información interna del vendedor.
5. **`GET /api/v1/catalog/products/{product_id}/shipping`** devuelve una **ventana** de entrega en días
   hábiles (preparación + tránsito, sin contar el día de hoy) y el coste de envío al comprador (hoy `0`). Los
   días salen de configuración (`SHIPPING_*`) y la respuesta lo declara en `source="configured_default"`: **no**
   es una tarifa de transportadora y la interfaz no puede presentarla como una promesa.
6. **`new_object_key(extension, prefix="products")` incluye el punto** y permite prefijo (`stores/` para logos):
   `products/<32 hex>.png`. Las claves ya guardadas sin punto siguen existiendo en el bucket (no se migran) y
   se pueden corregir subiendo de nuevo la imagen.

## Alternativas descartadas

- **Dejar que el frontend pidiera el stock variante por variante** (lo que hacía hasta ahora). Descartada: N
  peticiones por ficha, el endpoint de inventario expuesto públicamente y sin reservas descontadas.
- **Exponer el inventario completo** (`quantity` y `reserved_quantity`) al público. Descartada: las unidades
  reservadas de otras personas no son información del comprador; `available` responde a su pregunta real.
- **Devolver el stock solo en el detalle del producto** (y no en listados). Descartada: `VariantOut` lo usan el
  detalle y los listados del vendedor, y tener dos formas del mismo objeto obliga al frontend a distinguirlas.
- **Mostrar tiendas pendientes o suspendidas en el endpoint público.** Descartada: revela el estado de la
  solicitud del vendedor y permite ver catálogos que aún no deberían estar a la venta.
- **Inventar tarifas de envío por zona «realistas».** Descartada: es un dato de negocio que no existe (no hay
  tarifas ni transportadora). Se entrega lo que sí es cierto: una ventana estimada, configurable y declarada
  como tal, y el coste que hoy cobra el checkout (`0`).
- **Migrar las claves de imagen ya guardadas** (quitarles/añadirles el punto). Descartada: son objetos en S3 y
  la operación toca datos de producción; es más barato volver a subir lo que haga falta y que el frontend deje
  de aceptar el formato viejo cuando no queden claves así.

## Consecuencias

- La ficha de producto del frontend puede mostrar «Color: negro / Talla: M» y las unidades reales de cada
  presentación con **una sola** petición (`GET /catalog/products/{id}`).
- `total_available` permite deshabilitar «agregar al carrito» cuando no queda nada en ninguna presentación sin
  pedir el inventario.
- El frontend puede pintar «vendido por» y las estrellas de la tienda con `GET /stores/{store_id}`; los
  resultados de búsqueda todavía no traen tienda ni reputación (apartado 7, pendiente).
- La estimación de envío se podrá sustituir por tarifas reales cambiando solo `app/modules/shipping/estimates.py`.
- Al corregir la clave de las imágenes, el formato con punto pasa a ser el único que genera el backend. El
  frontend aún acepta el formato viejo para las imágenes ya subidas; cuando no queden, se puede quitar.
