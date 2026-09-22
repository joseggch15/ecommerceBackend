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

## Próximos pasos

- [ ] Fase 4: Monedas y conversión (detección por ubicación + API de tasas de cambio).
- [ ] Fase 5: Carrito.
- [ ] Fase 6: Órdenes y checkout.
- [ ] Fase 7: Pagos en sandbox y webhooks.
- [ ] Fase 8: Envíos.
- [ ] Fase 9: Reseñas, preguntas y reputación.
- [ ] Fase 10: Promociones y cupones.
- [ ] Fase 11: Notificaciones y tareas en segundo plano.
- [ ] Fase 12: Administración y moderación.
- [ ] Fase 13: Endurecimiento.

