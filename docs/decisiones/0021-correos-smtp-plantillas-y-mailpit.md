# 0021 · Correos reales: SMTP configurable, plantillas es/en y Mailpit en desarrollo

- **Fecha:** 22 de septiembre de 2026
- **Estado:** aceptada

## Contexto

Los tokens de verificación de correo y de recuperación de contraseña **solo se escribían en el log** de la API
(`AuthService`): no salía ningún correo. El usuario no podía completar el flujo desde el enlace del email, y el
frontend tiene pantallas (`/[locale]/verify-email`, `/[locale]/reset-password`) esperando ese enlace.

La infraestructura estaba a medias: `EmailSender` (interfaz + remitente de log), la cola de notificaciones en
Redis, el worker `POST /admin/notifications/process` y la tabla `notifications` con los campos del email
(decisión 0015). Faltaba el remitente SMTP real y las plantillas.

## Decisión

1. **Remitente SMTP con `aiosmtplib`** (`SmtpEmailSender`), elegido con `EMAIL_SENDER=smtp`. Es la librería
   asíncrona estándar para SMTP (MIT, tipada, sin dependencias) y encaja con el resto de la API: el registro y la
   recuperación no bloquean el event loop. **El remitente por defecto sigue siendo `logging`**: un `.env` sin
   tocar no manda correos a nadie.
2. **Variables nuevas en `.env`**: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_USE_TLS`,
   `SMTP_FROM` (opcional: si está vacío se usa `EMAIL_FROM`), `SMTP_TIMEOUT_SECONDS` y `FRONTEND_URL`.
   - `SMTP_USE_TLS` significa **TLS directo** (puerto 465). Con STARTTLS (587, o Mailpit en 1025) se deja en
     `false`: `aiosmtplib` lo activa solo si el servidor lo anuncia.
   - `FRONTEND_URL` es la URL pública del frontend y con ella se construyen los enlaces del correo
     (`{FRONTEND_URL}/{idioma}/verify-email?token=...` y `.../reset-password?token=...`). El correo enlaza al
     frontend (que canjea el token contra la API), no a la API directamente: es lo que hace el usuario.
3. **Mailpit en `docker-compose.yml`** (SMTP 1025, interfaz web 8025, base de datos en un volumen). Los correos
   de desarrollo se ven en `http://localhost:8025` y **no salen a Internet**.
4. **Plantillas en español e inglés** (`app/core/email_templates.py`), texto plano, con el idioma del perfil del
   usuario (`preferred_language`, aceptando variantes tipo `en-US`) y respaldo al idioma de la plataforma. Se
   usan dos plantillas: verificación de correo y recuperación de contraseña.
5. **El correo se envía por la cola que ya existía**: la fila de `notifications` guarda el asunto (`title`) y el
   cuerpo (`body`) ya renderizados, y el worker la manda. Dos motivos: no duplicar el mecanismo de envío y poder
   auditar «¿se avisó? ¿se envió?» en `GET /admin/notifications/emails`.
6. **Dos tipos de notificación nuevos** (`email_verification`, `password_reset`) marcados como **solo correo**
   (`EMAIL_ONLY_TYPES`): no son avisos in-app y `GET /notifications` no los muestra, así que un usuario recién
   registrado no ve una campana con «confirma tu correo» dentro de la aplicación.
7. **Migración `e7c9474064ee`**: `notifications.type` pasa de `VARCHAR(15)` a `VARCHAR(18)` porque
   `email_verification` (18) es más largo que el máximo anterior (`order_delivered`, 15).
8. **Los tokens dejan de escribirse en el log.** Ya viajan dentro del correo (y en desarrollo el cuerpo lo
   imprime el remitente `logging` al procesar la cola), así que registrarlos aparte solo añadía un secreto en
   claro en los logs.

## Alternativas descartadas

- **`smtplib` de la biblioteca estándar en un hilo** (`asyncio.to_thread`): cero dependencias nuevas, pero
  mezcla hilos con el event loop y hay que gestionar la conexión a mano. `aiosmtplib` es más simple y ya está
  probado en producción por mucha gente.
- **HTML en los correos**: se descarta por ahora. La interfaz de `EmailSender` solo lleva texto, y un texto bien
  escrito (con el enlace en su propia línea) se ve bien en cualquier cliente y en Mailpit. Añadir HTML
  significaría multipart, versión doble de cada plantilla y un cliente de correo menos fiel en las pruebas.
- **Poner la lógica del correo dentro del módulo de identidad**: descartada; las plantillas viven en `core`
  porque cualquier módulo (pedidos, envíos, vendedores) puede necesitar un correo con idioma.
- **Enviar el correo dentro del propio endpoint de registro** (síncrono): descartada; ya existe la cola y un
  fallo del servidor de correo no debe romper un registro.

## Consecuencias

- Con `EMAIL_SENDER=smtp` y Mailpit encendido, el flujo completo se prueba de verdad: registrarse, abrir el
  correo en `http://localhost:8025`, pulsar el enlace y ver el correo verificado en el frontend.
- Las pruebas usan el remitente `capturing` (en memoria) y el `conftest` fuerza `EMAIL_SENDER=logging` **antes**
  de importar la configuración: ninguna prueba abre una conexión SMTP, ni siquiera si el `.env` de la máquina
  apunta a un servidor real.
- Falta un correo de bienvenida tras verificar el correo y correos de pedidos con plantilla (hoy el aviso de
  pago usa el texto del aviso in-app). El patrón ya está montado: plantilla nueva, tipo nuevo y una llamada a
  `notify()`.
- Deuda conocida (de la decisión 0015): la cola de notificaciones no es un *outbox* en base de datos; el trabajo
  se encola antes del `commit`.
