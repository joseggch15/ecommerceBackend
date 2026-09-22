# Decisión 0015: Notificaciones y tareas en segundo plano (Fase 11)

**Fecha:** 2026-09-22
**Estado:** Aceptada

## Contexto

El comprador tiene que enterarse de lo que pasa con su pedido (pago confirmado, envío despachado, entrega) sin que la respuesta HTTP espere al proveedor de email, y sin acoplar el dominio a un servicio concreto.

## Decisiones

### 1. Una tabla para in-app y email
- `notifications` guarda el aviso in-app (`type`, `title`, `body`, `data` JSONB, `read_at`) y, si hay destinatario, los campos del email (`email_to`, `email_status`, `email_error`, `sent_at`).
- Motivo: el aviso y su email nacen del **mismo evento** y comparten título/cuerpo; una sola fila evita duplicar el hecho y simplifica la auditoría (“¿se avisó? ¿se envió?”).
- `type` es un `StrEnum` con valores estables (`order_paid`, `order_shipped`, `order_delivered`, `order_cancelled`, `welcome`) para que el frontend decida icono y destino.

### 2. Envío detrás de una interfaz (`EmailSender`)
- `LoggingEmailSender` (desarrollo: escribe en el log), `FailingEmailSender` (pruebas de reintento) y el registro `SENDERS` + `EMAIL_SENDER` en `.env`. Pasar a SES/SendGrid/SMTP es añadir una clase, no tocar el dominio.

### 3. Cola simple en Redis
- `app/core/queue.py`: lista FIFO (`RPUSH`/`LPOP`) con `enqueue`, `dequeue_batch`, `requeue` y `queue_size`. Es el patrón “cola de trabajos” sin dependencias nuevas.
- `POST /admin/notifications/process` consume la cola y hace de **worker de desarrollo** (en producción corre un proceso aparte: `while True: process_pending()`).
- Reintentos: en cada fallo se marca `failed` con el error y, si no se superaron 3 intentos, se **reencola** con `attempt + 1`.

### 4. Quien notifica no hace commit
- `NotificationService.notify()` **no** confirma la transacción: se llama desde dentro de transacciones de otros módulos (p. ej. `PaymentService._apply` al pasar a `succeeded`), y es el módulo dueño quien hace `commit`.
- Así el aviso comparte transacción con el hecho que lo provoca (no se notifica un pago que luego se revierte).

### 5. Compromiso aceptado (documentado)
- El trabajo se encola en Redis **antes** del `commit`. Si la transacción falla después, queda un trabajo huérfano: el worker no encuentra la notificación y lo cuenta como `failed` (no se pierde un aviso real, porque la notificación tampoco existe).
- Para producción lo correcto es un **outbox** en BD (insertar el trabajo en la misma transacción y que un proceso lo mueva a la cola). Queda anotado como deuda técnica.

### 6. Privacidad
- `GET /notifications` solo devuelve las del usuario autenticado; leer una ajena responde **404** (no filtra su existencia). Los endpoints de emails y de proceso de cola son **solo admin**.

## Consecuencias

- El checkout y los webhooks no esperan al email: la respuesta es rápida y el envío es reintentable.
- Los avisos in-app ya funcionan sin proveedor de email configurado (en desarrollo el “envío” es un log), así que la demo es completa.
- Los siguientes eventos (envío despachado, entrega, cancelación) se añaden llamando a `notify()` con su tipo: el patrón ya está probado.
