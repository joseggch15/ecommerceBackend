# 0020 · Prototipo realista: sin cobros reales por ahora (los pagos se quedan como están)

- **Fecha:** 22 de septiembre de 2026
- **Estado:** aceptada

## Contexto

El proyecto es un **prototipo que debe verse y comportarse como una tienda real**, pero todavía **no va a cobrar
dinero real**. La tarea anterior invirtió esfuerzo en un adaptador de Mercado Pago (preferencia, webhook
verificado, monto confirmado) y dejó pendiente un adaptador de Stripe, con la idea de que la F6 exigía una
pasarela real.

Ese esfuerzo **no se pierde** (el adaptador queda como pieza opcional, apagada y sin configurar), pero seguir
afinando pagos tiene un coste (tokens, credenciales, cuentas de comercio) que un prototipo no necesita.

## Decisión

1. **No se implementa Stripe** y **no se sigue afinando Mercado Pago**. No hay que crear credenciales.
2. **El proveedor por defecto sigue siendo `sandbox`** (`PAYMENT_PROVIDER=sandbox`), que simula pagos sin dinero
   real: `POST /orders/{id}/payments` + `POST /payments/{id}/simulate?outcome=succeeded|failed`.
3. **Se quitan de la lista de pendientes** los dos puntos de pagos: «pagos reales» (apartado 2) y cualquier
   integración de SDK de pasarela en el frontend. Si algún día se cobra de verdad, se conecta una pieza nueva
   (Mercado Pago ya está, o Wompi / PayU) **sin rehacer la tienda**, porque el dominio habla con
   `PaymentProvider` (decisión 0011 y 0019).
4. **Las reglas de seguridad que ya existen se quedan**: el monto lo calcula el servidor a partir de la orden,
   las transiciones de estado son explícitas y los webhooks se procesan una sola vez. No cuestan extra y hacen
   el prototipo más realista.
5. **La F6 (checkout) se desbloquea** con la pasarela de prueba: el checkout debe verse y comportarse como uno
   real (direcciones, envío, cupones, resumen y confirmación) y la pantalla de pago debe estar **claramente
   marcada como «modo de prueba»**, con botones para **aprobar o rechazar** el pago y poder probar los dos
   caminos. Nada de SDK de pasarela real.
6. **Prioridad del trabajo restante:** lo que se **ve** en la tienda (correos con Mailpit, producto por slug,
   reputación del vendedor y tienda en los resultados de búsqueda, filtros con conteos, avisos de precio y
   stock en el carrito, paginación de preguntas). El sitemap completo y el catálogo público de códigos de error
   solo si sobra contexto.

## Alternativas descartadas

- **Seguir con Stripe «por si acaso».** Descartada: Stripe no abre cuentas a empresas colombianas hoy y no hay
  intención de cobrar en el prototipo.
- **Quitar el adaptador de Mercado Pago.** Descartada: está hecho, probado y apagado; borrarlo sería tirar
  trabajo y cerrar la puerta a cobrar más adelante.
- **Dejar el checkout bloqueado hasta tener pasarela real.** Descartada: bloquea toda la F6 y el dueño quiere
  ver el flujo completo funcionando (con la pasarela de prueba) para poder evaluarlo.

## Consecuencias

- La F6 puede hacerse entera contra el sandbox: los dos caminos (aprobado y rechazado) se prueban con la
  pantalla de «modo de prueba».
- El frontend **no integra ningún SDK de pasarela**; cuando existan credenciales, la integración real es
  sustituir esa pantalla por el widget del proveedor y poner `PAYMENT_PROVIDER=mercadopago`.
- Deja de ser prioritario confirmar el protocolo de Mercado Pago con su documentación (sigue anotado en la
  decisión 0019 para el día que se cobre de verdad).
