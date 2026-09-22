# Decisión 0017: Endurecimiento (Fase 13)

**Fecha:** 2026-09-22
**Estado:** Aceptada

## Contexto

El backend está completo por fases (identidad → pagos → envíos → reseñas → cupones → notificaciones → administración). Antes de exponerlo hace falta cerrar la superficie: cabeceras, hosts permitidos, sondas de salud correctas y una imagen de producción sin root y sin herramientas de build.

## Decisiones

### 1. Cabeceras de seguridad en un middleware propio
- `SecurityHeadersMiddleware` (ASGI puro, como el de `request_id`) añade a **todas** las respuestas: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Permissions-Policy` restrictiva, `Cross-Origin-Resource-Policy: same-site` y `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`.
- **CSP estricta porque la API solo devuelve JSON**: no hay HTML que cargue recursos, así que `default-src 'none'` es correcto y evita que un error de contenido se interprete como documento.
- **HSTS solo en producción** (`ENVIRONMENT` en `production`/`prod`): en desarrollo se navega por `http://localhost` y HSTS dejaría el navegador forzando HTTPS.

### 2. Hosts permitidos configurables
- `TrustedHostMiddleware` con `ALLOWED_HOSTS` (por defecto `["*"]`, que se restringe en `.env.prod`). Protege contra *Host header injection* y enlaces envenenados.

### 3. Liveness y readiness separados
- `GET /health/live`: responde siempre que el proceso esté vivo, **sin tocar** PostgreSQL ni Redis → es lo que usa el `HEALTHCHECK` de Docker (si falla, el contenedor se reinicia).
- `GET /health/ready`: comprueba PostgreSQL y Redis; si algo falla devuelve **503** → es lo que usa el balanceador para decidir si enviar tráfico.
- `/health` se mantiene como alias de readiness para no romper clientes existentes.
- Confundir ambas cosas provoca reinicios en bucle cuando la base de datos está lenta: por eso van separadas.

### 4. Imagen de producción multi-stage y sin root
- **Etapa 1 (`builder`)**: instala dependencias con `uv sync --no-dev --no-install-project`. Al copiar solo `pyproject.toml`/`uv.lock` antes, cambiar el código no invalida la capa de dependencias.
- **Etapa 2 (`runtime`)**: `python:3.12-slim`, solo la `.venv` y el código, usuario **`appuser` (uid 10001, no root)**, `PYTHONDONTWRITEBYTECODE`/`PYTHONUNBUFFERED`.
- `HEALTHCHECK` con `urllib` (sin `curl` en la imagen) contra `/health/live`.
- `.dockerignore` excluye `.venv`, `.git`, tests, docs, cachés y `.env`.

### 5. Despliegue con migraciones antes de servir
- `docker-compose.prod.yml`: Postgres y Redis con `healthcheck`, y la API con `depends_on: {condition: service_healthy}`; el comando es `alembic upgrade head && uvicorn ...`, así que **si una migración falla el contenedor no arranca** (mejor fallar al desplegar que servir con esquema viejo).
- `--proxy-headers --forwarded-allow-ips=*` para que detrás de un proxy se registre la IP real (necesario para el rate limiting por IP).

## Fuera de alcance (y por qué)

- **Caché de listados/facetas**: la búsqueda ya usa índices GIN y paginación por cursor; cachear antes de **medir** añade invalidación que aún no se puede justificar. Se hará con el `SearchService` abstracto (Meilisearch/OpenSearch) si las métricas lo piden.
- **Pruebas de carga (k6/locust) y presupuestos de latencia**: necesitan un entorno estable; se ejecutarán contra `docker-compose.prod.yml`.
- **WAF, secretos en gestor externo y TLS**: responsabilidad de la plataforma de despliegue (los secretos ya viven en `.env` y no en el código).

## Consecuencias

- La API responde con cabeceras defensivas y hosts controlados sin tocar cada endpoint.
- Orquestadores pueden distinguir “proceso vivo” de “puede recibir tráfico”, evitando reinicios en bucle.
- El despliegue es reproducible: una imagen sin root, sin dev deps y con migraciones aplicadas antes de servir.
