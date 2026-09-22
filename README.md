# marketplace-api

Backend (API REST) de un **marketplace multi-vendedor**: vendedores publican productos, compradores los compran y la plataforma cobra una comisión por venta. El frontend (Next.js) se desarrolla por separado; este proyecto solo expone la API.

## Tecnologías

- Python 3.12+, FastAPI, SQLAlchemy 2.0 (async), PostgreSQL 16, Redis, Alembic, Pydantic v2.
- `uv` para dependencias. Docker para la base de datos y Redis. Ruff + mypy + pre-commit para calidad.

---

## Requisitos previos

Asegúrate de tener instalado:

| Herramienta | Comando para verificar |
|---|---|
| Python 3.12+ | `python --version` |
| uv | `uv --version` |
| Docker + Docker Compose | `docker --version` y `docker compose version` |
| Git | `git --version` |

> ⚠️ **Puertos:** este proyecto usa PostgreSQL en el puerto **5433** (para no chocar con un PostgreSQL local que ocupa el 5432) y Redis en el **6379**. Si tienes esos puertos ocupados, ajusta `docker-compose.yml` y `.env`.

---

## Cómo levantar el proyecto paso a paso

### 1. Entra a la carpeta del proyecto

```powershell
cd E:\ecommerce
```

### 2. Copia el archivo de configuración

```powershell
Copy-Item .env.example .env
```

Este archivo `.env` contiene las variables de entorno. **Nunca se sube a Git.**

### 3. Levanta PostgreSQL y Redis con Docker

```powershell
docker compose up -d
```

Para verificar que están corriendo:

```powershell
docker compose ps
```

Debes ver los contenedores `marketplace_postgres` y `marketplace_redis` con estado `running` (o `healthy`).

### 4. Instala las dependencias con uv

```powershell
uv sync
```

Esto crea el entorno virtual (`.venv`) e instala todas las dependencias del `pyproject.toml`.

### 5. Aplica las migraciones de la base de datos

```powershell
uv run alembic upgrade head
```

En la Fase 0 todavía no hay tablas de negocio, pero esto deja Alembic listo y verifica la conexión.

### 6. Levanta el servidor de desarrollo

```powershell
uv run uvicorn app.main:app --reload
```

### 7. Prueba la API

Abre en tu navegador:

- **Swagger (documentación interactiva):** http://127.0.0.1:8000/docs
- **Health check:** http://127.0.0.1:8000/api/v1/health

El health check debe devolver algo como:

```json
{
  "status": "ok",
  "checks": { "database": "ok", "redis": "ok" }
}
```

---

## Ejecutar las pruebas

```powershell
uv run pytest
```

## Calidad de código

```powershell
# Lint + formato (verifica)
uv run ruff check .
uv run ruff format --check .

# Tipos
uv run mypy app tests

# Corregir formato automáticamente (opcional)
uv run ruff check --fix .
uv run ruff format .
```

### pre-commit (opcional, recomendado)

Instala los hooks para que Ruff y mypy corran automáticamente antes de cada commit:

```powershell
uv run pre-commit install
```

---

## Estructura del proyecto

```
├── app/
│   ├── main.py              # Punto de entrada de FastAPI
│   ├── core/                # configuración, BD, Redis, logging, errores, middleware
│   ├── shared/              # utilidades compartidas (se llena en fases futuras)
│   └── api/v1/              # endpoints versionados (health check en Fase 0)
├── migrations/              # migraciones de Alembic
├── tests/                   # pruebas (misma estructura que app/)
├── docs/                    # PROYECTO.md, PROGRESO.md y decisiones/
├── docker-compose.yml       # PostgreSQL + Redis
├── pyproject.toml           # dependencias y configuración de herramientas
└── .env.example             # plantilla de variables de entorno
```

---

## Notas importantes

- **Formato de errores:** toda la API usa RFC 9457 (Problem Details) con un campo `code` estable.
- **Logs:** se emiten en JSON y cada petición lleva un `request_id` (también se devuelve en el header `X-Request-ID`).
- **Dinero:** siempre `Decimal`/`NUMERIC` con código ISO 4217 (nunca `float`).

Consulta `docs/PROYECTO.md` para el detalle completo del proyecto y `docs/PROGRESO.md` para el estado actual.
