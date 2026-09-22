# Decisión 0011: Pagos en sandbox y webhooks (Fase 7)

**Fecha:** 2026-09-22
**Estado:** Aceptada

## Contexto

El comprador paga **una sola vez** por la orden completa (que puede tener sub-órdenes de varios vendedores). Hace falta integrar una pasarela real sin acoplarse a ella, y procesar sus notificaciones sin duplicar cobros.

## Decisiones

### 1. `payments` (intento de pago) + `payment_events` (webhooks)
- **`payments`**: intento de pago de una orden (`provider`, `provider_reference` único, `amount`, `currency`, `status`, `checkout_url`, `paid_at`). Se permiten **varios intentos** por orden (reintentos tras un fallo); el estado autoritativo de la compra vive en `orders.payment_status`.
- **`payment_events`**: cada webhook se guarda **en crudo** (JSONB) con `UNIQUE(provider, provider_event_id)`. Repetir un evento devuelve `duplicate: true` y **no vuelve a aplicar el efecto**. Queda como registro de auditoría/conciliación (`processed_at`, `error`).
- Sin tablas de pagos en el módulo de órdenes: la separación es por módulo (decisión 0010).

### 2. La pasarela detrás de una interfaz
- `PaymentProvider` (ABC) expone `create_intent(...)` y `parse_webhook(raw_body, signature)`.
- `SandboxPaymentProvider` (nombre `sandbox`) simula el cobro: genera `sbx_<uuid>`, una URL de pago ficticia y sabe construir/parsear sus webhooks.
- `PROVIDERS` es un registro: añadir Stripe/MercadoPago es implementar la interfaz y registrarla; **el dominio no cambia**. El proveedor activo se elige con `PAYMENT_PROVIDER`.

### 3. Webhooks firmados y idempotentes
- Firma **HMAC-SHA256 del cuerpo crudo** en el header `X-Signature`, verificada con `hmac.compare_digest` (tiempo constante) **antes** de tocar la base de datos. Falta de firma o firma inválida → **401** `invalid_signature`.
- El endpoint siempre responde **200** con `{received, duplicate}` para que el proveedor no reintente en bucle; los eventos sin pago conocido se guardan con `error = payment_not_found` (auditoría) y no fallan.
- Idempotencia en la **base de datos** (no en Redis): la garantía debe sobrevivir a reinicios y caídas.

### 4. Simulador sandbox que reutiliza el camino real
`POST /payments/{id}/simulate?outcome=succeeded|failed|refunded` construye el payload, lo **firma** y llama al mismo `handle_webhook`. Así las pruebas y la demo ejercitan exactamente el código de producción. Solo se permite si el pago es de `sandbox` (si no, **409** `simulation_not_allowed`).

### 5. Máquina de estados y relación con la orden
- `payments.status`: `pending → processing → succeeded | failed | cancelled`, y `succeeded → refunded`.
- `succeeded` ⇒ `orders.payment_status = paid` y `orders.status: pending → paid`, con `paid_at`.
- `failed` ⇒ se guarda `failure_reason`; **la orden sigue pendiente** y admite otro intento.
- `refunded` ⇒ `orders.payment_status = refunded` y `orders.status = refunded`.
- Si el pago ya está `succeeded`, se ignoran los eventos posteriores salvo un reembolso (evita “despagar” por un webhook desordenado).

### 6. Reverso: pagar dos veces no es posible
- `POST /orders/{id}/payments` falla con **409** `order_already_paid` si la orden ya está pagada, y con **409** `order_not_payable` si no está `pending` (p. ej. cancelada).
- El intento lleva `Idempotency-Key` opcional (`UNIQUE(order_id, idempotency_key)`) para no crear dos intentos si el cliente reintenta.

## Consecuencias

- Integrar una pasarela real es trabajo de un solo archivo (adaptador) más credenciales.
- Ningún webhook, ni siquiera reenviado o desordenado, puede cobrar dos veces ni cobrar una orden pagada.
- La conciliación dispone del payload original firmado y de la fecha de procesamiento.
