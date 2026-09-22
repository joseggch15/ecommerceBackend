# Progreso del proyecto

## Fase 0: Fundamentos — COMPLETADA

- [x] Repositorio Git inicializado (`main`).
- [x] Estructura de carpetas del monolito modular.
- [x] `pyproject.toml` con uv y dependencias de la fase.
- [x] `docker-compose.yml` con PostgreSQL 16 y Redis (PostgreSQL en el puerto 5433).
- [x] Configuración con pydantic-settings, `.env.example` y `.gitignore`.
- [x] Conexión asíncrona a PostgreSQL + Alembic configurado.
- [x] Manejo global de errores RFC 9457, logging JSON con `request_id` y CORS.
- [x] Endpoint `GET /api/v1/health` que verifica PostgreSQL y Redis.
- [x] pytest configurado con pruebas del health check.
- [x] Ruff, mypy y pre-commit configurados.
- [x] `README.md`, `docs/PROYECTO.md`, `docs/PROGRESO.md` y `docs/decisiones/`.
- [x] `.clinerules` con las reglas no negociables y la forma de trabajar.

## Fase 1: Identidad — COMPLETADA

- [x] Dependencias nuevas: `PyJWT`, `pwdlib[argon2]`, `email-validator`.
- [x] `app/core/security.py` (Argon2id + JWT + tokens opacos).
- [x] `app/core/rate_limit.py` (ventana fija por IP con Redis).
- [x] Middleware ASGI puro para `request_id` (corrige un problema de `BaseHTTPMiddleware`).
- [x] Módulo `app/modules/identity/` con modelos, schemas, repositorios, servicio, dependencias y API.
- [x] Tablas: `users`, `user_profiles` (1:1), `addresses`, `refresh_tokens`, `user_tokens`.
- [x] Roles de plataforma: `customer` (por defecto) y `admin`. El rol `seller` se define en la Fase 2.
- [x] Registro, login (JWT + refresh rotativo), refresh, logout, verificación de email y recuperación de contraseña.
- [x] Perfil (`GET/PATCH /users/me`) y libreta de direcciones (CRUD con soft delete).
- [x] Rate limiting en register, login, forgot-password, resend-verification y reset-password.
- [x] Migración `ea689e90a5da` aplicada y verificada.
- [x] 18 pruebas (unitarias + integración contra PostgreSQL en Docker) en verde.

## Fase 2a: Vendedores y catálogo (sellers + categorías + atributos) — COMPLETADA

- [x] Módulo `sellers`: tienda (`stores`) con estados `pending/approved/rejected/suspended`.
- [x] Flujo de aprobación: el customer solicita su tienda; **solo el admin la aprueba/rechaza**.
- [x] Módulo `catalog`: categorías jerárquicas (árbol), atributos por categoría y comisión por categoría.
- [x] Tablas nuevas: `stores`, `categories`, `attributes`, `category_attributes`.
- [x] Comisión por categoría (`commission_rate` NUMERIC) + valor global por defecto (`DEFAULT_COMMISSION_RATE`).
- [x] Script `promote_admin` para ascender al dueño a admin.
- [x] Migración `f7ebb26b927a` aplicada con CHECK constraints (`store_status`, `attribute_type`).
- [x] 10 pruebas nuevas de integración (28 en total) en verde.

## Fase 2b: Productos, variantes e imágenes — COMPLETADA

- [x] Modelos `products`, `product_variants`, `product_images`, `variant_values`.
- [x] Productos con estados `draft/active/paused/closed` y transiciones válidas (publish/pause/close).
- [x] Variantes con SKU único, precio NUMERIC (12,2), precio de comparación y stock.
- [x] Valores de atributos por variante (EAV), listos para filtros por facetas (Fase 3).
- [x] Imágenes con MinIO + boto3 + URLs prefirmadas (`POST /catalog/images/upload-url`).
- [x] Autorización: solo el vendedor dueño (tienda aprobada) gestiona sus productos.
- [x] Migración `915dafad01ed` aplicada con CHECK `product_status`.
- [x] Dinero serializado como string con 2 decimales (Pydantic `Decimal` + `NUMERIC`).
- [x] 32 pruebas en verde (4 nuevas de productos).

## Fase 3a: Búsqueda — COMPLETADA

- [x] Módulo `search` con búsqueda por texto tolerante a errores (pg_trgm + full-text de PostgreSQL).
- [x] Filtros por facetas (categoría, marca, rango de precio), ordenamiento (relevancia/precio/reciente) y paginación por cursor.
- [x] Autocompletado de títulos (`GET /catalog/search/suggest`).
- [x] Interfaz `SearchService` abstracta, lista para migrar a Meilisearch/OpenSearch.
- [x] Migración `26a56be90086` (extensión `pg_trgm` + índices GIN).
- [x] 35 pruebas en verde (3 nuevas de búsqueda).

## Fase 3b: Inventario — COMPLETADA

- [x] Módulo `inventory` con `inventory_items` (quantity, reserved_quantity) e `inventory_movements` (ledger de auditoría).
- [x] El stock se movió de `product_variants` a `inventory_items` (inventory es dueño del stock).
- [x] Reservas atómicas con `SELECT ... FOR UPDATE` (cero sobreventa) y liberación de reservas.
- [x] Ajustes de stock con validación (nunca por debajo de lo reservado).
- [x] Al crear una variante, su stock inicial se registra en inventario automáticamente.
- [x] Migración `5972bb1db1b2` aplicada (los índices de búsqueda se preservaron).
- [x] 39 pruebas en verde (4 nuevas de inventario).

## Fase 4: Monedas y conversión — COMPLETADA

- [x] Lista de monedas **ISO 4217** (código, nombre, símbolo) — ~160 monedas.
- [x] **Proveedor de tasas de cambio** abstracto (`ExchangeRateProvider`) con implementación HTTP configurable por `.env`.
- [x] **Caché de tasas en Redis** (TTL configurable) para no llamar a la API en cada petición.
- [x] **Conversión con `Decimal`** (nunca float), redondeo a 2 decimales.
- [x] **Localización** por headers (`X-Country`, `Accept-Language`) → país, moneda, idioma y zona horaria.
- [x] Endpoints: `GET /currencies`, `GET /currencies/rates`, `POST /currencies/convert`, `GET /currencies/locale`.
- [x] Sin tablas nuevas (la preferencia del usuario ya vive en `user_profiles`, Fase 1).
- [x] 46 pruebas en verde (7 nuevas de monedas).

> La conversión es **informativa**: los precios se guardan y se cobran en la moneda del vendedor (por defecto COP).

## Fase 5: Carrito — COMPLETADA

- [x] Carrito **persistente** para usuarios registrados (`carts` + `cart_items`, `UNIQUE(cart_id, variant_id)`).
- [x] Carrito **temporal** para invitados en **Redis** (`guest_cart:{token}`, TTL 7 días).
- [x] Identificación del invitado con el header `X-Cart-Token` (se genera y se devuelve si falta).
- [x] **Fusión** del carrito de invitado al iniciar sesión (`POST /cart/merge`).
- [x] **Multi-vendedor**: un mismo carrito admite productos de varias tiendas.
- [x] Endpoints: `GET /cart`, `POST /cart/items`, `PATCH|DELETE /cart/items/{variant_id}`, `DELETE /cart`, `POST /cart/merge`.
- [x] Totales calculados en el servidor con `Decimal` y `MAX_QUANTITY = 100` por variante.
- [x] Migración `f015186b39ef` aplicada.
- [x] 51 pruebas en verde (5 nuevas de carrito).

> El carrito **no reserva stock** (eso ocurre al crear la orden, Fase 6).

## Fase 6: Órdenes y checkout — COMPLETADA

- [x] `orders` (compra del comprador, **un solo pago**) + `seller_orders` (sub-orden por vendedor) + `order_items`.
- [x] `POST /orders` (checkout): una transacción que valida, **reserva stock**, calcula totales y comisión, crea la orden y vacía el carrito.
- [x] **Idempotencia** con el header `Idempotency-Key` (`UNIQUE(user_id, idempotency_key)`).
- [x] **Snapshot** por línea: título, etiqueta de variante, SKU, precio unitario, moneda, tasa y monto de comisión.
- [x] Comisión efectiva = `categories.commission_rate` o la global; `payout_amount` = subtotal − comisión.
- [x] **Máquina de estados** de la sub-orden: `pending → processing → shipped → delivered` (+ `cancelled`).
- [x] `POST /orders/{id}/cancel` libera el stock reservado.
- [x] Endpoints: `POST /orders`, `GET /orders`, `GET /orders/{id}`, `POST /orders/{id}/cancel`, `GET /seller/orders`, `PATCH /seller/orders/{id}/status`.
- [x] Migración `b6d53d444b30` aplicada (los índices de búsqueda se preservaron).
- [x] 59 pruebas en verde (8 nuevas de órdenes).

> El pago se asocia a la **orden completa** (Fase 7); los envíos, a cada sub-orden (Fase 8).

## Fase 7: Pagos en sandbox y webhooks — COMPLETADA

- [x] `payments` (intento de pago de una orden) + `payment_events` (webhooks en crudo, `UNIQUE(provider, provider_event_id)`).
- [x] **Proveedor detrás de una interfaz** (`PaymentProvider`) con implementación `sandbox`; cambiar de pasarela es registrar otra.
- [x] **Webhooks firmados** con HMAC-SHA256 (`X-Signature`), verificación en tiempo constante e **idempotencia** por evento.
- [x] **Simulador sandbox** (`POST /payments/{id}/simulate`) que recorre el mismo camino que un webhook real.
- [x] Estados: `pending → processing → succeeded / failed / cancelled / refunded`, reflejados en `orders.payment_status` y `orders.status`.
- [x] Reintentos: un pago fallido deja la orden pendiente y permite crear otro intento.
- [x] Endpoints: `POST /orders/{id}/payments`, `GET /orders/{id}/payments`, `GET /payments/{id}`, `POST /payments/{id}/simulate`, `POST /webhooks/payments/{provider}`.
- [x] Migración `b5bdd281b2fc` aplicada (los índices de búsqueda se preservaron).
- [x] 67 pruebas en verde (8 nuevas de pagos).

## Fase 8: Envíos — COMPLETADA

- [x] `shipments` (un envío por sub-orden: transportadora, guía, URL de seguimiento, costo logístico y fechas) + `shipment_events` (línea de tiempo).
- [x] **Máquina de estados**: `pending → ready → shipped → in_transit → delivered` (+ `returned`/`cancelled`), con un evento por cada cambio.
- [x] **Sincronización**: `shipped`/`in_transit` mueven la sub-orden a `shipped`; al entregarse **todas** las sub-órdenes, la orden pasa a `completed`.
- [x] Endpoints: `POST|PATCH|GET /seller/orders/{id}/shipment`, `POST /seller/orders/{id}/shipment/status`, `GET /orders/{id}/shipments`.
- [x] El `cost` del envío es el **gasto logístico del vendedor**; la tarifa cobrada al comprador se define en el checkout.
- [x] Migración `98e2cc4cc799` aplicada (25 tablas y los índices de búsqueda intactos).
- [x] 72 pruebas en verde (5 nuevas de envíos).

> Pendiente para más adelante: tarifas de envío al comprador por zona/tabla del vendedor.

> ⚠️ **Incidente resuelto:** `ruff check --fix` borró los `import app.modules.*.models` de `migrations/env.py` (los veía como no usados). Sin ellos el metadata queda vacío y el autogenerate genera una migración que **dropea todas las tablas** (se generó y se descartó sin aplicar). Ahora `env.py` referencia los módulos en `_MODEL_MODULES` y **aborta si falta algún modelo** en `Base.metadata`. Revisa siempre el autogenerate antes de aplicar.

## Fase 9: Reseñas, preguntas y reputación — COMPLETADA

- [x] `reviews`: una reseña por comprador y producto, **solo si la compró y se la entregaron** (`order_item_id` de la línea de orden entregada).
- [x] **Reputación** denormalizada en `products` y `stores` (`rating_average`, `rating_count`), recalculada al crear, editar o borrar.
- [x] `questions` + `answers`: preguntas públicas y respuesta del vendedor (solo el dueño de la tienda del producto).
- [x] Endpoints: `POST /reviews`, `GET /products/{id}/reviews`, `PATCH|DELETE /reviews/{id}`, `POST|GET /products/{id}/questions`, `POST /questions/{id}/answers`.
- [x] `is_published` deja la moderación lista para la Fase 12; el listado de reseñas va por cursor.
- [x] Migración `164ce801f620` aplicada (28 tablas, índices GIN intactos).
- [x] 75 pruebas en verde (3 nuevas de reseñas).

> 🐞 **Bug resuelto:** usar `update()` masivo de SQLAlchemy para los agregados **expiraba** instancias de la sesión y al leerlas después fallaba con `MissingGreenlet` (I/O fuera del greenlet). Ahora se escriben sobre el objeto ORM (`select` + asignación) y, por seguridad, se hace `refresh` antes de responder.

## Fase 10: Promociones y cupones — COMPLETADA

- [x] `coupons`: código único, tipo `percent`/`fixed`, valor, mínimo de compra, vigencia (`starts_at`/`ends_at`), límites de uso totales y por usuario, tienda opcional y `is_active`.
- [x] `coupon_redemptions`: canje por usuario y orden con `UNIQUE(coupon_id, order_id)` (idempotente) y `used_count` en el cupón.
- [x] Aplicación **dentro de la transacción del checkout**: el descuento se **prorratea por vendedor** y la **comisión se calcula sobre el neto**.
- [x] Nuevas columnas `orders.discount_total` y `seller_orders.discount_amount`; el total de la orden descuenta el cupón.
- [x] Endpoints: `POST /coupons`, `GET /coupons`, `POST /coupons/{id}/deactivate` (solo admin) y `POST /coupons/validate` (vista previa sobre el carrito).
- [x] Errores claros: **404** `coupon_not_found`; **409** `coupon_exists`, `coupon_not_started`, `coupon_expired`, `min_purchase_not_met`, `coupon_usage_limit`, `coupon_user_limit`.
- [x] Migración `4a5022ef3817` aplicada (30 tablas, índices GIN intactos).
- [x] 79 pruebas en verde (4 nuevas de cupones).

> Pendiente: el cupón puede restringirse a una tienda (`store_id`) pero todavía **no** se filtra por líneas del carrito; y los descuentos por producto/oferta por tiempo quedan para más adelante.

## Fase 11: Notificaciones y tareas en segundo plano — COMPLETADA

- [x] `notifications`: aviso **in-app** por usuario y, opcionalmente, el email asociado (`email_to`, `email_status`, `sent_at`, `email_error`).
- [x] **Cola de trabajos en Redis** (`app/core/queue.py`): FIFO con `enqueue`/`dequeue_batch`/`requeue`/`queue_size`; cambiar a Celery/RQ no toca el dominio.
- [x] **`EmailSender` detrás de una interfaz** (`logging` en desarrollo, `failing` para probar reintentos) elegido con `EMAIL_SENDER`.
- [x] **Hilo real:** al confirmarse el pago (`order_paid`) se crea el aviso del comprador y se encola su email; `POST /admin/notifications/process` hace de worker con **reintentos (hasta 3)** reencolando.
- [x] Endpoints: `GET /notifications` (con `unread_count` y `only_unread`), `POST /notifications/{id}/read`, `POST /notifications/read-all`, `GET /admin/notifications/emails`, `POST /admin/notifications/process` (admin).
- [x] Migración `03cb2f1cc4f0` aplicada (31 tablas, índices GIN intactos).
- [x] 82 pruebas en verde (3 nuevas de notificaciones).

> Compromiso conocido: la cola se escribe en Redis **dentro** de la transacción (no hay outbox transaccional). Si la transacción falla tras encolar, el trabajo queda huérfano y el worker lo marca `failed`; para producción conviene un **outbox** en BD.

## Fase 12: Administración y moderación — COMPLETADA

- [x] `admin_actions`: **libro de auditoría** de cada acción (quién, qué, sobre qué, por qué y datos extra).
- [x] **Moderación de productos**: `POST /admin/products/{id}/suspend` (→ `paused`, sale de la venta) y `/restore` (→ `active`).
- [x] **Moderación de tiendas**: `POST /admin/stores/{id}/suspend` (→ `suspended`) y `/restore` (→ `approved`).
- [x] **Moderación de reseñas**: `POST /admin/reviews/{id}/hide` y `/publish` usando el `is_published` de la Fase 9, **recalculando la reputación** del producto y de la tienda.
- [x] **Tablero** `GET /admin/metrics`: usuarios, tiendas, productos activos, órdenes por estado, **GMV**, **comisión acumulada** y **top 5 vendedores**.
- [x] `GET /admin/actions`: auditoría paginada. Todo el prefijo `/admin` exige rol **admin** (401 sin token, 403 con rol customer).
- [x] Migración `6ea2b3f185b6` aplicada (32 tablas, índices GIN intactos).
- [x] 85 pruebas en verde (3 nuevas de administración).

> Los cambios de estado respetan las máquinas de estados ya existentes (catálogo y tiendas) y quedan auditados; el `reason` es opcional pero recomendado desde el panel.

## Fase 13: Endurecimiento (seguridad y despliegue) — COMPLETADA

- [x] **Cabeceras de seguridad** en toda respuesta: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Permissions-Policy`, `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` y `Cross-Origin-Resource-Policy`; **HSTS solo en producción**.
- [x] **`TrustedHostMiddleware`** con `ALLOWED_HOSTS` configurable (por defecto `*` en desarrollo).
- [x] **Sondas separadas**: `GET /health/live` (sin dependencias) y `GET /health/ready` (PostgreSQL + Redis, 503 si algo falla); `/health` sigue siendo alias de readiness.
- [x] **Imagen de producción**: `Dockerfile` multi-stage (uv, sin dev deps, usuario **no root** `appuser`, `.venv` cacheable y `HEALTHCHECK` contra `/health/live`) + `.dockerignore`.
- [x] **`docker-compose.prod.yml`**: Postgres y Redis con `healthcheck` y `depends_on: service_healthy`; la API corre `alembic upgrade head` **antes** de servir tráfico.
- [x] 89 pruebas en verde (4 nuevas de endurecimiento).

> Fuera del alcance de esta entrega (documentado en la decisión 0017): caché de listados, pruebas de carga y presupuestos de latencia.

## Hoja de ruta completada

Las **14 fases (0 a 13)** del plan están implementadas y commiteadas.

## Tarea de pendientes del frontend (22/09/2026) — 1ª parte COMPLETADA

Encargo: resolver los bloqueantes de la F6 del frontend (`E:\ecommerce-web\docs/PENDIENTES-BACKEND.md`),
empezando por pagos, datos públicos de tienda y envío, y stock y atributos de las variantes.

- [x] **Reglas operativas heredadas del frontend** en `.clinerules`: terminal, `esperar.ps1`, credenciales,
      eficiencia (umbral de 250k tokens, pruebas solo de lo cambiado, sin preguntas de flujo, resumen de 25
      líneas, `git push` tras cada cierre) y **vista previa en el puerto 3001**.
- [x] **Vista previa** levantada y dejada encendida: backend en `127.0.0.1:8000` y `pnpm dev -p 3001` en el
      frontend (`http://localhost:3001/es`).
- [x] **`VariantOut` con `stock`, `available` y `attribute_values[]`** y `ProductOut.total_available`, en dos
      consultas por producto (no N+1). `available` descuenta lo reservado. Apartado 10 — **resuelto**.
- [x] **`GET /api/v1/stores/{store_id}` público** (nombre, logo, reputación y pedidos entregados; solo tiendas
      aprobadas) y **`GET /api/v1/catalog/products/{id}/shipping`** con ventana de entrega estimada y coste.
      Apartado 11 — **resuelto**.
- [x] **`new_object_key()` con el punto y prefijo parametrizable** (`products/<32 hex>.png`, `stores/…`).
      Apartado 8 — **resuelto**.
- [x] **Adaptador de Mercado Pago** (`app/modules/payments/mercadopago.py`): preferencia con clave de
      idempotencia derivada de la orden y del intento, webhook que verifica la firma y **consulta el pago** en el
      proveedor para confirmar estado, monto y moneda antes de dar la orden por pagada. Apartado 2 — **resuelto en
      el backend** (Stripe queda como adaptador secundario). Decisión `0019`.
- [x] `httpx` pasa a dependencia principal; `.env.example` con las variables de Mercado Pago vacías.
- [x] Pruebas: 31 del catálogo/inventario/vendedores/envíos y 16 de pagos, todas en verde; Ruff limpio.
- [x] **Decisión pendiente de confirmar por el dueño:** los tres detalles del protocolo de Mercado Pago
      (encabezado y plantilla de firma, decimales del COP) quedaron **en configuración** porque la documentación
      oficial no fue accesible desde el entorno de desarrollo.

### Lo que queda de la lista (para la siguiente tarea)

- **Correos reales** (apartado 5): SMTP configurable desde `.env`, plantillas en español e inglés según
  `preferred_language` y **Mailpit** en `docker-compose.yml` (SMTP 1025, web 8025).
- **Mejoras de tienda:** conteos por faceta (3), catálogo público de códigos de error (4), reputación y tienda en
  los resultados de búsqueda (7), producto por slug (9), paginación de preguntas (12), listado para el sitemap
  (13) y avisos de precio/stock en el carrito (14).
- **El resto (solo si sobra contexto):** exigir correo verificado para comprar (6, decisión del dueño), tokens en
  el registro (15), sitemap completo (13) y catálogo público de códigos de error (4), más la **suite completa**
  (`uv run pytest -q`) y **mypy**.
- **Pagos: CONGELADOS** (decisión `0020-prototipo-sin-pagos-reales.md`): el prototipo no cobra dinero real, el
  adaptador de Mercado Pago queda opcional y sin configurar y **no se implementa Stripe**. La F6 se hace con la
  pasarela de prueba y el checkout se marca como «modo de prueba».

