# Decisión 0003: Identidad — roles, perfil y autenticación

**Fecha:** 2026-09-21
**Estado:** Aceptada

## Contexto

En la Fase 1 se construye el módulo de identidad. Había que decidir cómo modelar los roles (comprador/vendedor/admin), dónde guardar las preferencias de usuario, y el diseño de autenticación (JWT).

## Decisiones

### 1. Roles: `customer` y `admin` (el "vendedor" NO es un rol)
- `users.role` es un enum de **plataforma**: `customer` (por defecto) y `admin`.
- Todo usuario registrado es `customer` (puede comprar).
- **"Vendedor" no es un rol**: es una entidad del módulo `sellers` (Fase 2), con tienda, verificación y comisión. Así un usuario puede ser comprador y vendedor a la vez, y `identity` no conoce la lógica de vendedores (frontera del monolito modular).

### 2. Preferencias en tabla separada `user_profiles` (1:1)
- `users` guarda solo identidad/autenticación (email, hash, rol) → búsquedas de login rápidas.
- `user_profiles` guarda `full_name`, `preferred_currency`, `preferred_language`, `timezone` y futuros campos de perfil (avatar, bio...).
- Se crea en la misma transacción que el usuario.

### 3. Enums: `StrEnum` + `VARCHAR` con CHECK (sin ENUM nativo de PostgreSQL)
- `enum.StrEnum` (Python 3.11+) en lugar de `str, Enum`.
- En BD usamos `sa.Enum(..., native_enum=False)`: columna VARCHAR + CHECK constraint. Es más fácil de migrar que el ENUM nativo (que obliga a `ALTER TYPE`).

### 4. Autenticación: access JWT + refresh opaco rotativo
- **Access token**: JWT HS256 de 15 min (autocontenido, `sub` = id de usuario).
- **Refresh token**: string opaco aleatorio (7 días), guardado **hasheado** en `refresh_tokens`. Rotativo: cada `/refresh` revoca el anterior y emite uno nuevo.
- `PyJWT` para JWT; `pwdlib[argon2]` (Argon2id) para contraseñas.

### 5. Rate limiting: ventana fija por IP con Redis
- Contador con `INCR` + `EXPIRE` en Redis, por IP del cliente.
- Aplicado a register, login, forgot-password, resend-verification y reset-password.

### 6. Middleware ASGI puro para `request_id`
- Se descartó `BaseHTTPMiddleware` (deja tareas en segundo plano sin cerrar, lo que falla con `httpx.ASGITransport` en tests).
- Se usa un **middleware ASGI puro** que: guarda el `request_id` en `request.state`, lo agrega al contexto de logging y lo devuelve en el header `X-Request-ID`.

### 7. Emails simulados
- En la Fase 1 los tokens de verificación/reset se **registran en logs** (no se envían por email). El envío real llega en la Fase 11 (notificaciones).

## Consecuencias

- Modelo escalable: comprador/vendedor independientes; perfil extensible sin tocar `users`.
- Seguridad: contraseñas con Argon2id, refresh revocable/rotativo, rate limiting en endpoints sensibles.
- Verificación de email no bloquea el login en esta fase (se puede endurecer después).
