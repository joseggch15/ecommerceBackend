# 0024 · Lagunas de la F8 y la F9: stock del vendedor, directorio de usuarios y moderación de preguntas

- **Fecha:** 22 de septiembre de 2026
- **Estado:** aceptada

## Contexto

La F8 (panel del vendedor) y la F9 (panel de administración) quedaron **bloqueadas** por tres lagunas
reales del backend, anotadas en `E:\ecommerce-web\docs\SIGUIENTE-PROMPT.md`:

1. **El vendedor no podía cambiar el stock** después de crear la variante: `/inventory/items/{id}/adjust`
   es solo de administración y `ProductUpdate` no acepta variantes, así que la pantalla tenía que mostrar
   el stock en **solo lectura** y explicar por qué.
2. **No había listado de usuarios**: la administración solo tenía contadores en `/admin/metrics`, así que la
   pantalla «ver usuarios» no se podía construir.
3. **No había moderación de preguntas**: solo el vendedor podía responder; si una pregunta era inapropiada no
   había forma de ocultarla (las reseñas sí se moderaban desde la F6).

Se resuelven **solo añadiendo endpoints**: no se toca ningún contrato existente ni se necesita migración
(las tres cosas usan tablas que ya existen).

## Decisión

### 1. `PATCH /api/v1/catalog/products/{product_id}/variants/{variant_id}/stock`

- **Cuerpo `{"stock": int}` es un valor absoluto, no un incremento.** El vendedor escribe lo que tiene en el
  almacén («12 unidades»); obligarle a calcular el delta es trasladarle un cálculo del servidor (y el
  `.clinerules` dice que el servidor calcula siempre, nunca el cliente). *Alternativa descartada:* reutilizar
  `StockAdjustRequest` (`delta`), que es la forma de la administración.
- **El delta lo calcula el servidor** en `InventoryService.set_quantity`, con `SELECT ... FOR UPDATE`, y lo
  anota en el ledger (`inventory_movements`, `reason = "seller_update"`). Si el valor no cambia, **no se
  escribe movimiento** (delta 0 no ensucia la auditoría).
- **Nunca por debajo de lo reservado:** `409 insufficient_stock`, igual que el ajuste de administración. Esas
  unidades ya están vendidas y pendientes de entrega.
- **Autorización**: `get_approved_store` (tienda aprobada, y con el interruptor `REQUIRE_VERIFIED_EMAIL`
  encendido también correo verificado) **más** la propiedad del producto (`get_owned` → `403 forbidden`).
  Un comprador recibe `403 seller_required`; sin sesión, `401`. *Alternativa descartada:* añadir un endpoint
  de administración «déjame ajustar si es tu tienda»; rompía la separación de módulos y la auditoría de admin.
- **Responde `ProductOut` completo** (no solo la variante): el panel refresca de una vez el stock, el
  `total_available` y el resto de la tarjeta, como en `PATCH /catalog/products/{id}`.

### 2. `GET /api/v1/admin/users` (solo administradores)

- **Paginación por cursor** (`created_at DESC, id DESC`, `next_cursor` en base64), como el resto de listados
  grandes del proyecto; no se usa `offset`, que se descuadra cuando entran usuarios nuevos.
- **`q` busca por correo (contiene, `ILIKE`)** y **`role` filtra por rol de plataforma**. Se añade además
  `full_name`, y si la cuenta tiene tienda, `store_id`, `store_name` y `store_status`: **no existe un rol
  «vendedor»** (es un usuario con tienda), así que sin ese dato el panel no podría distinguir a quien vende.
- **Cero credenciales**: `AdminUserRepository` **no lee** `password_hash`, `refresh_tokens` ni `user_tokens`;
  el schema `AdminUserOut` no tiene esos campos. El riesgo no se mitiga filtrando al serializar, se elimina
  no consultando. Lo cubre una prueba que comprueba las claves exactas de la respuesta y que el cuerpo no
  contiene las palabras `password`, `token`, `argon2` ni `hash`.
- Las cuentas con borrado lógico (`users.deleted_at`) no aparecen.

### 3. Moderación de preguntas: `GET /admin/questions`, `POST /admin/questions/{id}/hide`, `…/publish`

- **Se copia el patrón de las reseñas** (F6): mismos verbos (`hide` / `publish`), misma auditoría en
  `admin_actions` (`question.hide` / `question.publish`, `target_type = "question"`) y misma respuesta
  (`AdminActionOut`). *Alternativa descartada:* llamarlos `/restore`, que habría dejado dos nombres distintos
  para la misma acción dentro del mismo panel.
- **El listado incluye las ocultas** (son justo lo que se modera) con filtro opcional `published`, el
  `product_title` (el moderador necesita saber sobre qué producto es la pregunta) y `answer_count`. El título
  y el recuento se traen en dos consultas agregadas, sin N+1.
- **Ocultar la pregunta la saca del listado público con sus respuestas dentro** (van anidadas) **y también
  impide que el vendedor la responda**, porque la búsqueda de la pregunta para responder ya exigía
  `is_published`. No se borra nada: republicar la devuelve tal cual.

### Nota sobre los cursores

`_encode_cursor` / `_decode_cursor` viven ahora también en `app/modules/admin/service.py`, como ya hacían
`orders`, `reviews`, `search` y `catalog`. Se ha preferido **duplicar el helper** (seis líneas) antes que
extraerlo a `app/shared/` y tocar cuatro módulos que ya funcionan y están probados: el objetivo de esta
tanda es no romper contratos. Si algún día hace falta un quinto sitio, el refactor se hace de una vez y con
las pruebas delante.

## Consecuencias

- **F8** puede cambiar el stock de sus variantes (ya no hace falta mostrarlo en solo lectura) → endpoint y
  campos documentados en `E:\ecommerce-web\docs\SIGUIENTE-PROMPT.md`.
- **F9** puede listar usuarios con búsqueda y filtro, y moderar preguntas igual que reseñas.
- Pruebas nuevas: 4 de integración del stock (`tests/modules/catalog/test_variant_stock.py`, incluida la
  autorización de otro vendedor y de un comprador) y 6 de administración (`tests/modules/admin/test_admin_f9.py`).
- Sin migración: `DB` intacta (`alembic upgrade head` sigue siendo el mismo `head`).
