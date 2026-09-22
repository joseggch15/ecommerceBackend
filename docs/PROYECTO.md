# marketplace-api — Documento del proyecto

> Este documento es la fuente de verdad del proyecto. Léelo en cada sesión antes de trabajar.

## 1. Resumen

Backend (API REST) de un **marketplace multi-vendedor**: muchos vendedores publican productos, muchos compradores los compran y la plataforma cobra una comisión por cada venta. El frontend (Next.js en Vercel) se hace aparte; este proyecto solo expone la API.

## 2. Datos del negocio

| Dato | Valor |
|---|---|
| Nombre del proyecto | **marketplace-api** |
| País y moneda principal | Colombia / **COP** |
| Pasarelas de pago | Mercado Pago y Stripe (modo sandbox) |
| Idioma de la API | Inglés (los mensajes van con un `code` estable para traducir en el frontend) |
| Idioma de la interfaz | Se adapta a la ubicación del usuario; el usuario puede cambiarlo |
| Zona horaria | Se adapta a la ubicación; internamente todo se guarda en **UTC** |

### Multi-moneda
- Detección automática por ubicación del usuario (ej. USA → USD) como valor inicial.
- El usuario puede cambiar manualmente moneda, idioma y zona horaria (como en Amazon).
- Conversión mediante **API de tasas de cambio** (con caché en Redis).
- **Regla de oro:** los precios se guardan y se cobran en la moneda del vendedor (por defecto COP). La conversión es **informativa** para el comprador.
- En la Fase 1 se guardan `preferred_currency`, `preferred_language` y `timezone` en el perfil del usuario (el backend los necesita para enviar emails en su idioma).

## 3. Arquitectura: monolito modular

- Una sola aplicación desplegable, dividida en módulos de negocio con fronteras claras.
- Cada módulo es dueño de sus tablas. Ningún módulo lee/escribe las tablas de otro directamente.
- Comunicación entre módulos solo por servicios públicos o eventos internos de dominio.
- Capas por módulo: `api → service → repository → models`. Los schemas Pydantic definen entrada/salida. La lógica de negocio NUNCA va en las rutas.
- Principios SOLID, inyección de dependencias con `Depends`, YAGNI.

## 4. Stack tecnológico

- Python 3.12+ con type hints en todo.
- `uv` para dependencias y entorno virtual (`pyproject.toml`).
- FastAPI + Pydantic v2.
- SQLAlchemy 2.0 asíncrono + asyncpg.
- PostgreSQL 16+ como base de datos principal.
- Alembic para migraciones (la BD nunca se modifica a mano).
- Redis para caché, rate limiting, carritos de invitados y colas.
- Celery con Redis (desde la fase de notificaciones).
- Búsqueda: PostgreSQL full-text + pg_trgm (listo para migrar a Meilisearch/OpenSearch).
- Imágenes: S3-compatible (MinIO) con URLs prefirmadas (desde la fase de catálogo).
- Pruebas: pytest, pytest-asyncio, httpx.
- Calidad: Ruff, mypy, pre-commit.
- Docker y Docker Compose.
- Configuración con pydantic-settings y variables de entorno.

### Librerías de seguridad/autenticación (fases futuras)
- **PyJWT** (en lugar de python-jose, que tiene mantenimiento irregular).
- **pwdlib[argon2]** (en lugar de passlib, que no publica versiones desde 2020).
- `redis` incluye sus propios tipos (no usar types-redis); PyJWT no necesita stubs.

## 5. Estructura de referencia

```
ecommerce-backend/  (raíz del repo: E:\ecommerce)
├── app/
│   ├── main.py
│   ├── core/          # configuración, base de datos, Redis, seguridad, logging, errores
│   ├── shared/        # paginación, dinero, eventos, tipos base
│   ├── api/           # enrutamiento versionado (/api/v1)
│   └── modules/       # módulos de negocio (se crean en sus fases)
│       ├── identity/  # api.py, schemas.py, models.py, repository.py, service.py
│       ├── sellers/
│       ├── catalog/
│       ├── inventory/
│       ├── search/
│       ├── cart/
│       ├── orders/
│       ├── payments/
│       ├── shipping/
│       ├── reviews/
│       ├── promotions/
│       └── notifications/
├── migrations/
├── tests/             # misma estructura que app/
├── docs/
├── docker-compose.yml
├── pyproject.toml
├── .env.example
└── README.md
```

## 6. Módulos de negocio (resumen)

1. **identity** — registro, login, verificación de email, recuperación de contraseña, roles de plataforma (`customer`/`admin`), perfil (nombre + preferencias) en tabla 1:1, libreta de direcciones. El rol `seller` pertenece al módulo `sellers` (Fase 2).
2. **sellers** — tienda, verificación, reputación (ventas, cancelaciones, reclamos), comisión configurable por categoría.
3. **catalog** — categorías jerárquicas, atributos por categoría, productos con variantes y SKU, imágenes, estados de publicación.
4. **inventory** — stock por SKU, reservas temporales en checkout, cero sobreventa.
5. **search** — texto tolerante a errores, facetas, ordenamiento, autocompletado.
6. **cart** — persistente (registrados), temporal (invitados), fusión al iniciar sesión, multi-vendedor.
7. **orders** — checkout, sub-órdenes por vendedor, máquina de estados, cancelaciones, devoluciones, disputas.
8. **payments** — abstracción de pasarelas (Adapter), webhooks, reembolsos, comisiones, liquidación.
9. **shipping** — costo y métodos de envío, guía y seguimiento, proveedores intercambiables.
10. **reviews** — reseñas solo de compras verificadas, preguntas y respuestas.
11. **promotions** — cupones, descuentos, ofertas por tiempo limitado.
12. **notifications** — emails y notificaciones por eventos, en segundo plano.

## 7. Reglas técnicas no negociables

(Ver `.clinerules` para el detalle completo.)

- **Dinero:** nunca float; Decimal + NUMERIC + ISO 4217. El servidor calcula todo. Snapshots en líneas de orden.
- **Concurrencia:** transacciones con `SELECT ... FOR UPDATE`/bloqueo optimista; idempotencia (`Idempotency-Key`, webhooks); máquina de estados.
- **Seguridad OWASP:** Argon2, JWT corto + refresh rotativo, autorización por recurso, rate limiting, CORS, secretos en `.env`, sin datos de tarjetas, firma de webhooks.
- **API:** versionada `/api/v1`, UUID, paginación por cursor, errores RFC 9457 con `code` estable, OpenAPI completa.
- **Datos:** `created_at`/`updated_at` UTC, soft delete, índices para consultas reales.
- **Observabilidad:** logs JSON con `request_id`, health check de PostgreSQL y Redis.
- **Código:** inglés en código, español en docstrings; pruebas unitarias + integración (PostgreSQL en Docker).

## 8. Hoja de ruta por fases

| Fase | Contenido |
|---|---|
| 0 | Fundamentos (estructura, Docker, config, BD, migraciones, health, pruebas, calidad) |
| 1 | Identidad (usuarios, roles, autenticación, direcciones, **preferencias de usuario**) |
| 2 | Vendedores y catálogo (tiendas, categorías, atributos, productos, variantes, imágenes) |
| 3 | Inventario y búsqueda |
| 4 | **Monedas y conversión** (detección por ubicación + API de tasas de cambio) |
| 5 | Carrito |
| 6 | Órdenes y checkout |
| 7 | Pagos en sandbox y webhooks |
| 8 | Envíos |
| 9 | Reseñas, preguntas y reputación |
| 10 | Promociones y cupones |
| 11 | Notificaciones y tareas en segundo plano |
| 12 | Administración y moderación |
| 13 | Endurecimiento (caché, rendimiento, pruebas de carga, seguridad, despliegue) |

## 9. Definición de "terminado" por fase

- El código funciona y las migraciones se aplican sin errores.
- Todas las pruebas pasan; Ruff y mypy sin errores.
- Endpoints documentados en `/docs` (Swagger).
- `docs/PROGRESO.md` actualizado.
- Resumen en español: qué se construyó, cómo probarlo desde `/docs`, y mensaje de commit sugerido.

## 10. Puertos locales

- PostgreSQL: **5433** en el host (el 5432 lo ocupa un PostgreSQL local de Windows) → 5432 en el contenedor.
- Redis: **6379**.
- MinIO (S3-compatible): API en **9000** y consola web en **9001** (http://localhost:9001).
