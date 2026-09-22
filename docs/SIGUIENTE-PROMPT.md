# Prompt de continuación — marketplace-api (backend)

Pega esto al abrir una tarea nueva en `E:\ecommerce`. Es corto a propósito: **las reglas están en
`.clinerules`** (léelo, no se repite aquí) y el detalle del trabajo hecho está en `docs/PROGRESO.md`.

## Reglas (obligatorias)

- Trabajo **autónomo, sin preguntas de flujo**: si hay dos opciones razonables, elige la recomendada,
  regístrala en `docs/decisiones/` y sigue.
- **Umbral de contexto: 250k tokens.** Al acercarte, detente con el proyecto funcionando y todo commiteado,
  actualiza `docs/PROGRESO.md` y reescribe este archivo con el mensaje para continuar.
- **Vista previa (puerto 3001):** comprueba si escucha; si no, levanta el backend y `pnpm dev -p 3001` en
  `E:\ecommerce-web`. **Déjalos encendidos al terminar** y escribe la URL exacta de lo que cambies. El 3001 es
  solo para el dueño: las pruebas usan el 3000.
- Durante el desarrollo, **solo las pruebas de lo que cambias**; la suite completa, Ruff y mypy **una vez al
  final** (y otra solo si hubo correcciones). `git commit` **y** `git push` en cada repositorio que cambies.
- Resumen final de **máximo 25 líneas**.
- No toques el código del frontend: solo sus `docs/PENDIENTES-BACKEND.md` y `docs/SIGUIENTE-PROMPT.md`.

## Estado (22/09/2026)

De los **15 apartados** de `E:\ecommerce-web\docs/PENDIENTES-BACKEND.md`: resueltos el **3, 5, 7, 8, 9, 10, 11,
12 y 14**; el **1** queda parcial y el **2** (pagos reales) **sale de la lista**
(`docs/decisiones/0020-prototipo-sin-pagos-reales.md`).
Últimos commits del backend: `c1a08c8` (correos), `031c79b`, `6bd5302`; del frontend: `81d2d30`, `879d0fd`.
Entorno: backend en `127.0.0.1:8000` (con `.env` local: `EMAIL_SENDER=smtp` → Mailpit, worker de correos
encendido, `FRONTEND_URL=http://localhost:3001`), Mailpit en **http://localhost:8025** y vista previa en
`http://localhost:3001/es`.

### Lo recién hecho (contexto imprescindible)

- **Correos reales** (decisión `0021`): SMTP con `aiosmtplib`, plantillas es/en, cola de notificaciones
  reutilizada, worker en el proceso de la API (`NOTIFICATION_WORKER_ENABLED=true` en desarrollo) y tipos
  **solo correo** (`EMAIL_ONLY_TYPES`) que no salen en `GET /notifications`.
- **Tienda** (decisión `0022`): facetas con conteos reales en `/catalog/search`, `store_name` + reputación en los
  resultados, `GET /catalog/products/by-slug/{slug}`, cursor en las preguntas y carrito con `available`,
  `added_unit_price`, `price_changed`, `thumbnail`, `attribute_values` y **409 `insufficient_stock`**.
- Ojo al tocar el carrito: el precio de cuando se añadió vive en `cart_items.unit_price_snapshot` y, para
  invitados, dentro del valor JSON de Redis (`quantity` + `unit_price`; se sigue leyendo el entero antiguo).

## Trabajo pendiente, en este orden

### 1. Lo que queda de la lista del frontend

- **(13) Listado público del catálogo para el sitemap**: `GET /catalog/products` hoy es del vendedor (devuelve
  *su* catálogo). Hace falta un listado público por cursor (`q`/`cursor`/`limit`) con `slug` y `updated_at` para
  recorrer el catálogo entero, y decidir si el sitemap se pagina en varios archivos.
- **(4) Catálogo público de códigos de error** (por ejemplo `docs/ERRORES.md`): inventariar los `code` estables
  (hoy se descubren leyendo el código) y mantenerlo al día; si se puede, publicarlo también en OpenAPI.
- **(1) URLs de imágenes** (queda parcial): devolver `url` resuelta (o presignada) en `ProductImageOut` y en el
  `thumbnail` de la búsqueda y del carrito. Hasta entonces el frontend usa su proxy `/api/media/[key]`.
- **(6)** `email_not_verified` si el dueño decide exigir verificación para comprar (es su decisión: si no lo ha
  dicho, déjalo pendiente y anótalo).
- **(15)** Devolver tokens (o iniciar sesión) en el registro.

### 2. Datos que faltan para la interfaz (no inventar)

- **`sold_count`** (unidades vendidas) para la insignia «más vendido» del frontend: exige agregar líneas de orden
  entregadas y un índice nuevo. No se añadió en la tanda anterior; si el dueño lo pide, se hace con una consulta
  agregada (no con un contador denormalizado sin pruebas).
- **Correos de pedido con plantilla**: hoy el aviso de pago usa el texto del aviso in-app.

### 3. Cierre de cada tanda

- `uv run pytest -q`, `uv run ruff check app tests`, `uv run mypy app tests`, actualizar `docs/PROGRESO.md` y el
  `PENDIENTES-BACKEND.md` del frontend, commit y push en ambos repositorios.
- **Nada de pagos:** no implementes Stripe ni sigas afinando Mercado Pago (decisión 0020).

## Avisos para el próximo que toque esto

- **`alembic revision --autogenerate` mete dos `drop_index` falsos** (`ix_products_search_vector` e
  `ix_products_title_trgm`, creados con SQL crudo en `26a56be90086`): hay que borrarlos a mano antes de aplicar.
- Los ficheros generados por Alembic traen **CRLF**: para reescribirlos, bórralos y vuelve a crearlos (o usa
  `WriteAllText` con UTF8 sin BOM); las ediciones por bloques del editor no encuentran el texto.
- Los índices de búsqueda y las facetas dependen de `pg_trgm` y de los índices GIN: si algún día se recrean las
  tablas en pruebas, el `conftest` ya hace `CREATE EXTENSION IF NOT EXISTS pg_trgm`.

