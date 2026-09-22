# Decisión 0004: Vendedores y catálogo (Fase 2a)

**Fecha:** 2026-09-21
**Estado:** Aceptada

## Contexto

En la Fase 2 se construyen los módulos `sellers` (tiendas) y `catalog` (categorías, atributos y, luego, productos). Había que decidir cómo se aprueba a un vendedor, dónde vive la comisión y cómo modelar los atributos.

## Decisiones

### 1. Aprobación de vendedores: el admin decide
- Un `customer` **solicita** su tienda (`POST /sellers/me` → estado `pending`).
- **Solo el admin** (dueño del software) puede `approve`/`reject`.
- La verificación KYC real queda para más adelante; por ahora es un `status`.
- Esto permite controlar quién vende (modelo "marketplace curado") y escalar luego a un flujo con documentos.

### 2. "Vendedor" como tienda (1:1 con usuario)
- `stores` tiene `user_id` único: un usuario tiene como máximo una tienda.
- El rol `customer`/`admin` (identity) y la tienda (sellers) están separados: ser vendedor no cambia el rol de plataforma.

### 3. Comisión por categoría con valor global
- `categories.commission_rate` (`NUMERIC(5,2)`, opcional).
- Valor global por defecto en `config.DEFAULT_COMMISSION_RATE` (10%).
- Comisión efectiva = `category.commission_rate` si existe, si no el global. Escalable: se puede sobrescribir por categoría sin tocar código.

### 4. Atributos por categoría (EAV)
- `attributes` (nombre + tipo `text/number/select`) globales.
- `category_attributes` relaciona categoría ↔ atributo (con `is_required`).
- Permite filtrar por facetas más adelante (Fase 3, búsqueda). En Fase 2b se usarán para los valores de las variantes.

### 5. Categorías jerárquicas
- `categories.parent_id` autorreferenciado (árbol). Sin relación ORM autorreferencial (se consulta por `parent_id`) para evitar complejidad innecesaria.
- No se puede eliminar una categoría con hijos (409).

## Consecuencias

- Control de quién vende (aprobación del admin) y separación clara de responsabilidades entre módulos.
- Catálogo listo para productos/variantes (2b) y búsqueda por facetas (Fase 3).
- Comisión flexible y escalable.
