# 0022 · Tienda: producto por slug, facetas reales, avisos en el carrito y paginación de preguntas

- **Fecha:** 22 de septiembre de 2026
- **Estado:** aceptada

## Contexto

Tarea de pendientes del frontend (`E:\ecommerce-web\docs/PENDIENTES-BACKEND.md`, apartados 3, 7, 9, 12 y 14).
Lo que faltaba era lo que se **ve** en la tienda: la URL bonita del producto, la reputación y la tienda en los
resultados de búsqueda, los conteos de la barra de filtros, los avisos de precio y stock en el carrito, y la
paginación de las preguntas (que ya devolvía un `next_cursor` siempre nulo).

## Decisión

1. **Producto por slug**: `GET /api/v1/catalog/products/by-slug/{slug}` (público, misma respuesta que la
   consulta por id). Se declara **antes** de `/catalog/products/{product_id}` para que la ruta no se confunda
   con un identificador y se apoya en el índice único de `products.slug`.
2. **Reputación y tienda en la búsqueda**: `ProductSearchItem` añade `rating_average`, `review_count` (el
   `rating_count` denormalizado) y `store_name`. Se resuelven con **subconsultas escalares** (`SELECT ... LIMIT
   1`), igual que `min_price` y `thumbnail`, en vez de con un `JOIN`: un JOIN con reseñas multiplicaría las filas
   y obligaría a agrupar la consulta entera.
3. **Facetas en la propia respuesta** (`facets`), no en un endpoint aparte: la interfaz necesita los items y los
   conteos a la vez, y un endpoint separado significaría dos peticiones con los mismos filtros.
   - `categories`: `category_id`, `name` y `count` (solo categorías con resultados, máximo 20).
   - `brands`: marca y `count` (las marcas vacías no son una faceta, máximo 20).
   - `price`: `min` y `max` **reales** de los resultados. **No se inventan tramos** (0-50k, 50k-100k…): dependen
     de la moneda y del catálogo, así que el frontend construye su deslizador con datos reales.
   - Cada faceta se cuenta con **los demás filtros aplicados y el suyo propio excluido** (comportamiento
     multi-selección: «si añado esta categoría, ¿cuántos resultados tendré?»).
4. **Carrito con avisos**:
   - `cart_items.unit_price_snapshot` (NUMERIC, migración `dd68961274d7`) guarda el precio de la variante
     **cuando se añadió** la línea; `CartItemOut` expone `added_unit_price` y `price_changed` (nunca `true` si no
     hay precio de referencia, para no inventar avisos).
   - En el carrito de invitado (Redis) el valor de cada línea pasa a ser **JSON** (`quantity` + `unit_price`); se
     sigue aceptando el entero del formato anterior para no perder los carritos vivos.
   - `CartItemOut` añade además `available` (stock menos reservas), `thumbnail` (primera imagen) y
     `attribute_values` (color, talla), todo en tres consultas por carrito (nada de N+1).
   - `POST /cart/items` y `PATCH /cart/items/{variant_id}` responden **409 `insufficient_stock`** cuando la
     cantidad pedida supera lo disponible (antes se aceptaban hasta 100 unidades sin mirar el inventario).
5. **Preguntas paginadas con el mismo cursor que las reseñas** (`created_at` + `id`, en base64):
   `GET /products/{id}/questions` acepta `cursor` y devuelve un `next_cursor` real.

## Alternativas descartadas

- **Validar el stock solo en el checkout.** Descartada: el carrito mostraría líneas imposibles y el comprador se
  enteraría al final. Ahora se rechaza al pedir (409) y, si el stock cambia **después**, la línea lo avisa con
  `available` y el checkout sigue rechazando (la prueba del checkout simula justo eso).
- **Guardar el precio del invitado en un hash aparte de Redis.** Descartada: dos estructuras que hay que
  mantener sincronizadas para un dato pequeño. El JSON con compatibilidad hacia atrás es más simple.
- **Un endpoint `GET /catalog/search/facets`.** Descartada: duplica filtros y respuestas; la barra de filtros
  necesita los dos datos juntos.
- **Tramos de precio predefinidos.** Descartada: serían números inventados que además cambian con la moneda.
- **`sold_count` (unidades vendidas) y la insignia «más vendido».** No se añade: exige agregar líneas de orden
  entregadas y un índice nuevo; se queda anotado como pendiente en vez de devolver un dato a medias.

## Consecuencias

- La barra de filtros del frontend puede pintar conteos reales y deshabilitar facetas sin resultados.
- El carrito puede avisar de cambios de precio y de falta de stock **sin inventar nada**, y la ficha del producto
  puede enlazarse por slug.
- Dos pruebas existentes cambiaron de escenario porque el comportamiento mejoró: el límite de 100 unidades
  necesita stock suficiente, y el rollback del checkout ahora se provoca **reduciendo el stock después** de
  añadir al carrito (antes se creaba un carrito con más unidades de las que había, algo que ya no es posible).
