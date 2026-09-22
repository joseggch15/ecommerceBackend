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

## Próximos pasos

- [ ] **Fase 2: Vendedores y catálogo** — tiendas, verificación del vendedor (tú como creador), categorías, atributos, productos, variantes e imágenes.
- [ ] Fase 3: Inventario y búsqueda.
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

