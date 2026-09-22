# 0019 · Pagos con Mercado Pago: preferencia con idempotencia, webhook verificado y monto confirmado

- **Fecha:** 22 de septiembre de 2026 (tarea de pendientes del frontend, bloqueante de la F6)
- **Estado:** aceptada

## Contexto

El frontend quiere cobrar de verdad (apartado 2 de `docs/PENDIENTES-BACKEND.md`). El dueño del producto fijó
**Mercado Pago como pasarela principal** (Stripe no abre cuentas a empresas colombianas hoy) y dejó Stripe como
adaptador secundario para más adelante; Wompi o PayU podrán añadirse sin rehacer nada porque el dominio habla
con la interfaz `PaymentProvider`, no con una pasarela concreta.

El módulo de pagos ya existía con un proveedor **sandbox** y webhooks firmados con HMAC-SHA256, así que el
trabajo fue añadir un adaptador real sin tocar la máquina de estados ni la idempotencia de eventos.

## Decisión

1. **Adaptador por la API REST del proveedor**, no por su SDK: se usa `httpx` (ya estaba en el proyecto) con un
   `transport` **inyectable**, de modo que las pruebas usan `httpx.MockTransport` y **nunca** llaman a la API
   real.
2. **La interfaz `PaymentProvider` pasa a ser asíncrona** y el webhook recibe **todos los encabezados**: cada
   pasarela firma a su manera (el sandbox usa `X-Signature` con HMAC del cuerpo; Mercado Pago usa `x-signature`
   + `x-request-id`), y el adaptador es quien conoce su protocolo.
3. **Idempotencia derivada de la orden y del intento.** Si el cliente manda `Idempotency-Key` se respeta; si no,
   la clave es `order-<id>-<n>`, donde `n` es el número de intento. Un intento **en curso** se devuelve tal cual
   (doble clic, red que se cae → no hay dos cobros) y un intento **fallido no bloquea** el reintento. La clave
   viaja al proveedor en su encabezado de idempotencia.
4. **El webhook no se cree: se confirma.** Se verifica la firma (comparación en tiempo constante) y después se
   **consulta el pago en la API del proveedor**; el estado, el monto y la moneda que se aplican son los que
   responde esa consulta. Si el monto o la moneda no coinciden con el intento de pago, el pago queda `failed`
   (`amount_mismatch`) y la orden **no** se marca como pagada.
5. **El pago se localiza por la orden**, no por la referencia: Mercado Pago avisa con el id del **pago**, que no
   existe cuando creamos la preferencia. Se busca el intento pendiente de esa orden y, si el proveedor no manda
   `external_reference`, se cae a la referencia guardada (sandbox).
6. **El detalle del protocolo vive en configuración** (`MERCADOPAGO_SIGNATURE_HEADER`,
   `MERCADOPAGO_REQUEST_ID_HEADER`, `MERCADOPAGO_IDEMPOTENCY_HEADER`, `MERCADOPAGO_SIGNATURE_TEMPLATE`,
   `MERCADOPAGO_AMOUNT_MODE`) con los valores que documenta Mercado Pago para las notificaciones v2
   (`x-signature` con `ts=...,v1=...`, plantilla `id:{data_id};request-id:{request_id};ts:{ts};`,
   `X-Idempotency-Key`) y monto **entero** por defecto (el peso colombiano no usa centavos en la práctica).
7. **El sandbox sigue siendo el proveedor por defecto** (`PAYMENT_PROVIDER=sandbox`) hasta que existan
   credenciales: con `PAYMENT_PROVIDER=mercadopago` y sin token, la API responde 503
   `payment_provider_not_configured` en lugar de intentar cobrar.

### ⚠️ Lo que **no** se pudo verificar (y hay que confirmar antes de cobrar)

La documentación oficial de Mercado Pago **no fue accesible desde este entorno** (las URLs responden 404 o
exigen JavaScript al pedirlas sin navegador; también falló el repositorio del SDK). Por eso los tres puntos que
el dueño pidió verificar quedaron **en configuración**, con los valores estándar como valor por defecto:

1. Nombre del encabezado de firma (`x-signature`) y su formato (`ts=...,v1=...`).
2. Plantilla exacta de la cadena firmada (`id:{data_id};request-id:{request_id};ts:{ts};`).
3. Regla de decimales del COP (entero sin centavos vs. dos decimales).

Confirmarlos (o corregirlos) es cambiar variables de entorno; no hay que tocar código.

## Alternativas descartadas

- **Creer el cuerpo del webhook** (estado y monto tal como llegan). Descartada: un aviso se puede reenviar o
  manipular; el monto se confirma contra el proveedor y se compara con el de la orden.
- **Usar un `Idempotency-Key` por orden sin contar intentos.** Descartada al ver que rompía el reintento tras un
  pago fallido (lo detectó una prueba existente: el reintento devolvía el mismo intento fallido).
- **Integrar el SDK oficial del proveedor.** Descartada por ahora: añade una dependencia y su cliente no está
  pensado para asyncio; `httpx` ya está en el proyecto y basta para dos llamadas.
- **Marcar la orden como pagada al recibir un `approved` aunque el monto no coincida.** Descartada: es
  exactamente el fraude que hay que evitar (pagar 1 COP por una orden de 129.900).
- **Enviar el monto como `float` en el dominio.** Descartada: el monto de la orden se calcula con `Decimal`; el
  `float` solo aparece, si se elige el modo `decimal`, en el JSON que se envía al proveedor.

## Consecuencias

- La F6 puede crear la preferencia y recibir el webhook; falta el **frontend** (Checkout Bricks con la
  `public_key` y la `preference_id`) y decidir si se usan refunds por API.
- Stripe queda como adaptador pendiente: implementar `StripePaymentProvider` y registrarlo, sin tocar nada más.
- Las pruebas de pagos (16) cubren: firma válida/inválida, confirmación del pago contra la API, monto que no
  coincide, credenciales ausentes y los modos de monto. Ninguna llama a la API real.
