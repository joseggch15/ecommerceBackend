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

De los **15 apartados** de `E:\ecommerce-web\docs/PENDIENTES-BACKEND.md`: resueltos el **2** (Mercado Pago), **8**
(claves de imagen con punto), **10** (stock y atributos en las variantes) y **11** (tienda pública y envío
estimado); el **1** queda parcial. Últimos commits: `9f49103` (pagos), `48c9827` (catálogo público).
Entorno: backend en `127.0.0.1:8000`, vista previa en `http://localhost:3001/es`.

## Trabajo pendiente, en este orden

### 1. Correos reales (apartado 5) — lo que más valor tiene

- Hoy los tokens de verificación y de recuperación **solo se escriben en los logs** (`AuthService`): no sale
  ningún correo.
- Añadir un **remitente SMTP configurable** desde `.env` (`EMAIL_SENDER=smtp`, `SMTP_HOST`, `SMTP_PORT`,
  `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `SMTP_FROM`) manteniendo `EMAIL_SENDER=logging` por defecto.
- Plantillas en **español e inglés** según el `preferred_language` del perfil del usuario, con el enlace
  apuntando al frontend (`{FRONTEND_URL}/{locale}/verify-email?token=…` y `/reset-password?token=…`). Hace falta
  una variable nueva para la URL pública del frontend.
- **Mailpit en `docker-compose.yml`** (SMTP 1025, interfaz web 8025) para ver los correos en desarrollo sin
  enviarlos de verdad. Deja la URL de Mailpit en el resumen.
- Reutilizar la cola de notificaciones que ya existe (`notifications`) para el envío; las pruebas usan un
  remitente falso, **nunca** SMTP real.

### 2. Mejoras de tienda

- **(3) Conteos por faceta** en `GET /catalog/search` (categoría, marca y rango de precio).
- **(7) Reputación y tienda en `ProductSearchItem`** (`rating_average`, `review_count`, `store_name`).
- **(9) `GET /catalog/products/by-slug/{slug}`** (consulta por índice único).
- **(12) Paginación por cursor en las preguntas** (`GET /products/{id}/questions?cursor=…`).
- **(13) Listado público del catálogo** para el sitemap (`GET /catalog/products?cursor=&limit=`).
- **(14) Avisos de precio y stock en el carrito**: añadir `available` y `price_changed` a `CartItemOut` y
  rechazar con `insufficient_stock` cuando la cantidad supere lo disponible.
- **(1)** Si se puede, devolver `url` resuelta (o presignada) en `ProductImageOut` y en el `thumbnail` de la
  búsqueda.
- **(4)** Publicar el catálogo de códigos de error estable (por ejemplo `docs/ERRORES.md`).

### 3. El resto

- **(5/6)** `email_not_verified` si el dueño decide exigir verificación para comprar (es su decisión: pregúntale
  solo esto, o déjalo pendiente y anótalo).
- **(15)** Devolver tokens (o iniciar sesión) en el registro.
- **Stripe** como adaptador secundario, **solo si todo lo anterior está terminado**.
- Cierre: `uv run pytest -q`, `uv run ruff check app tests`, `uv run mypy app tests`, actualizar
  `docs/PROGRESO.md` y el `PENDIENTES-BACKEND.md` del frontend, commit y push en ambos repositorios.

## Aviso que no se puede olvidar (Mercado Pago)

⚠️ La documentación oficial de Mercado Pago **no fue accesible** desde este entorno, así que tres detalles del
protocolo quedaron **en configuración** con sus valores por defecto:

1. `MERCADOPAGO_SIGNATURE_HEADER` (`x-signature`) y su formato (`ts=...,v1=...`).
2. `MERCADOPAGO_SIGNATURE_TEMPLATE` (`id:{data_id};request-id:{request_id};ts:{ts};`).
3. `MERCADOPAGO_AMOUNT_MODE` (`integer`: monto sin centavos para COP).

**Confírmalos con la documentación oficial antes de cobrar de verdad**; si cambian, se corrigen en `.env` sin
tocar código. El proveedor por defecto sigue siendo `sandbox` (con `PAYMENT_PROVIDER=mercadopago` y sin token, la
API responde 503 `payment_provider_not_configured`). Decisión completa: `docs/decisiones/0019-pagos-mercado-pago.md`.
