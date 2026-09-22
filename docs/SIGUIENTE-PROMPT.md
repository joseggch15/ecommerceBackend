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

De los **15 apartados** de `E:\ecommerce-web\docs/PENDIENTES-BACKEND.md`: resueltos el **5** (correos con
Mailpit), el **8**, el **10** y el **11**; el **1** queda parcial y el **2** (pagos reales) **sale de la lista**
(`docs/decisiones/0020-prototipo-sin-pagos-reales.md`).
Últimos commits del backend: `879d0fd`, `031c79b`, `6bd5302`; del frontend: `879d0fd`, `d639852`.
Entorno: backend en `127.0.0.1:8000` (con `.env` local: `EMAIL_SENDER=smtp` → Mailpit, worker de correos
encendido, `FRONTEND_URL=http://localhost:3001`), Mailpit en **http://localhost:8025** y vista previa en
`http://localhost:3001/es`.

### Lo recién hecho (contexto imprescindible)

- **Correos reales** (decisión `0021-correos-smtp-plantillas-y-mailpit.md`): remitente SMTP con `aiosmtplib`,
  plantillas es/en (`app/core/email_templates.py`), cola de notificaciones reutilizada, worker en el proceso de
  la API cuando `NOTIFICATION_WORKER_ENABLED=true`, y `notifications.type` ampliado (`email_verification`,
  `password_reset`), que son tipos **solo correo** (`EMAIL_ONLY_TYPES`, no salen en `GET /notifications`).
- Si tocas algo del envío, **las pruebas nunca deben usar SMTP real** (el `conftest` fuerza `EMAIL_SENDER=logging`
  y las de integración usan el remitente `capturing`).

## Trabajo pendiente, en este orden

### 1. Mejoras de tienda (lo que se ve en la tienda)

- **(9) `GET /catalog/products/by-slug/{slug}`**: consulta por el índice único del slug (el frontend ya enlaza
  `/p/{productId}`; el slug es más bonito y estable para compartir).
- **(7) Reputación y tienda en los resultados de búsqueda**: `rating_average`, `review_count` y `store_name` en
  `ProductSearchItem` (el frontend no puede pintar la tarjeta completa sin ellos), sin consultas N+1.
- **(3) Conteos por faceta** en `GET /catalog/search`: cuántos resultados hay por categoría, por marca y por rango
  de precio, con los **mismos filtros** que la búsqueda.
- **(14) Avisos de precio y stock en el carrito**: `available` y `price_changed` en `CartItemOut` y rechazar con
  `insufficient_stock` cuando la cantidad pedida supere lo disponible (hoy acepta hasta 100 sin comprobar nada).
- **(12) Paginación por cursor en las preguntas** (`GET /products/{id}/questions?cursor=…`), igual que las
  reseñas, y devolver un `next_cursor` real.
- **(1) URLs de imágenes** (queda parcial): devolver `url` resuelta (o presignada) en `ProductImageOut` y en el
  `thumbnail` de la búsqueda. Hasta entonces el frontend usa su proxy `/api/media/[key]`.

### 2. El resto (solo si sobra contexto)

- **(13) Listado público del catálogo** para el sitemap (`GET /catalog/products?cursor=&limit=`) y el sitemap
  completo (varias páginas).
- **(4)** Publicar el catálogo de códigos de error estable (por ejemplo `docs/ERRORES.md`).
- **(6)** `email_not_verified` si el dueño decide exigir verificación para comprar (es su decisión: si no lo ha
  dicho, déjalo pendiente y anótalo).
- **(15)** Devolver tokens (o iniciar sesión) en el registro.
- **Nada de pagos:** no implementes Stripe ni sigas afinando Mercado Pago (decisión 0020).
- Cierre: `uv run pytest -q`, `uv run ruff check app tests`, `uv run mypy app tests`, actualizar
  `docs/PROGRESO.md` y el `PENDIENTES-BACKEND.md` del frontend, commit y push en ambos repositorios.

## Pendiente menor anotado (no urgente)

- Correos de pedido con plantilla: hoy el aviso de pago usa el texto del aviso in-app. Cuando haya plantillas
  para pedidos, se añaden en `app/core/email_templates.py` y en `EMAIL_ONLY_TYPES` si no son aviso in-app.
- La cola de notificaciones no es un *outbox* en base de datos (deuda conocida de la decisión 0015).

