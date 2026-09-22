# Decisión 0006: Búsqueda de productos (Fase 3a)

**Fecha:** 2026-09-22
**Estado:** Aceptada

## Contexto

En la Fase 3a se construye la búsqueda de productos: texto tolerante a errores, filtros por facetas, ordenamiento, paginación por cursor y autocompletado.

## Decisiones

### 1. PostgreSQL: `pg_trgm` + full-text (como está previsto)
- `pg_trgm` para similitud por trigramas (`similarity()`, `ILIKE`) → tolera errores de escritura.
- Full-text (`to_tsvector`/`plainto_tsquery`) para coincidencia por palabras, con índice GIN de expresión.
- Índice GIN trigram (`gin_trgm_ops`) sobre `products.title`.
- La extensión `pg_trgm` se habilita por migración y también en la BD de pruebas (setup de tests).

### 2. Interfaz abstracta `SearchService`
- La lógica de búsqueda queda detrás de `SearchService`, de modo que migrar a Meilisearch/OpenSearch solo requiere reimplementar ese servicio, sin tocar la API.

### 3. Precio de búsqueda = precio mínimo de la variante
- El filtro y ordenamiento por precio usan el mínimo precio entre las variantes (subconsulta). Evita precios inconsistentes entre variantes.

### 4. Paginación por cursor (keyset)
- El cursor codifica (clave de orden, id) en base64. Orden estable con `id` como desempate.

## Consecuencias

- Búsqueda usable desde ya por los compradores, con camino claro de evolución a un motor dedicado.
- El setup de pruebas crea `pg_trgm` (las extensiones no se crean con `create_all`).
