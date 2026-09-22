# 0023 · Cierre de la lista del frontend: correo verificado opcional, registro con sesión, `sold_count` y listado público del catálogo

- **Fecha:** 22 de septiembre de 2026
- **Estado:** aceptada

## Contexto

Última tanda de la lista de `E:\ecommerce-web\docs\PENDIENTES-BACKEND.md`. Quedaban el apartado 6 (¿exigir el
correo verificado?), el 13 (listado del catálogo para el sitemap) y el 15 (el registro no devolvía tokens), más
un dato que faltaba para la interfaz: `sold_count` (unidades vendidas) para la insignia «más vendido». El dueño
decidió además **descartar** los apartados 1 (URLs de imágenes) y 4 (catálogo público de códigos de error): el
proxy de medios del frontend ya resuelve las imágenes y los códigos se conocen leyendo el código.

El proyecto es un **prototipo** que se enseña y se prueba a mano: exigir la verificación del correo obligaría a
abrir Mailpit en cada prueba, y esa fricción no aporta nada mientras no haya usuarios reales.

## Decisión

1. **Correo verificado como interruptor, apagado por defecto** (`REQUIRE_VERIFIED_EMAIL=false`).
   - El correo de verificación se sigue enviando y el token se sigue pudiendo canjear: nada se ha borrado.
   - Con el interruptor **encendido** se exige el correo verificado para **vender** (`POST /sellers/me` y todas
     las acciones de venta, que cuelgan de `get_approved_store`) y para **publicar** (`POST /reviews` y
     `POST /products/{id}/questions`).
   - El rechazo es **403 `email_not_verified`**, un código estable más para que la interfaz ofrezca «reenviar el
     correo» en lugar de mostrar un error genérico.
   - La dependencia vive en `app/modules/identity/deps.py` (`require_verified_email`) y se encadena a
     `get_current_user`: leer el interruptor en cada petición es lo que permite encenderlo sin reiniciar el código,
     solo cambiando el `.env`. Editar o borrar la propia reseña **no** lo exige (ya está publicada).
2. **El registro deja la sesión iniciada**: `POST /auth/register` responde `RegisterOut`
   (`user` + `access_token` + `refresh_token` + `token_type`), es decir los mismos tokens que el login y, además,
   el usuario. Así el BFF del frontend guarda la sesión sin una petición extra a `GET /users/me`, y el carrito del
   invitado se puede fusionar en el mismo paso (`POST /cart/merge`, apartado 15).
3. **`sold_count` (unidades vendidas) en `ProductSearchItem` y `ProductOut`**: subconsulta **agregada** sobre
   `order_items` de órdenes en estado `paid` o `completed`, correlacionada con el producto
   (`app/modules/orders/repository.py::paid_units_subquery`). Un reembolso deja la orden en `refunded` y sus
   unidades **dejan** de contar. Se añade el índice `ix_order_items_product_id` (migración `8f0a63d4c1b9`) porque
   el agregado filtra por producto.
4. **Listado público del catálogo para el sitemap**: `GET /api/v1/catalog/products/public` (público, por cursor),
   con `q`, `cursor` y `limit` (máximo 500, por defecto 100). Devuelve `id`, `slug`, `title` y `updated_at` de los
   productos **activos**, del más reciente al más antiguo (`updated_at` es el `lastmod` del sitemap). Se declara
   antes de `/catalog/products/{product_id}` para que la ruta no se confunda con un identificador.
5. **Descartado para el prototipo:** apartado 1 (URLs de imágenes resueltas o prefirmadas) y apartado 4 (catálogo
   público de códigos de error). El frontend usa su proxy `/api/media/[key]` para las imágenes y los `code`
   estables se leen del código; si el proyecto pasa a ser real, ambos se retoman sin cambiar nada de lo de hoy.

## Alternativas descartadas

- **Registro que devuelve solo `TokenPair`** (lo más parecido al login literal). Se descarta porque el BFF
  necesita el usuario para construir su cookie de sesión: serían dos peticiones por registro. `RegisterOut` es un
  superconjunto y sigue siendo «los tokens igual que el login».
- **Un parámetro `?login=true` en el registro** para elegir si inicia sesión. Descartada: mete estado en la URL
  para algo que el producto ya decidió (registrarse inicia sesión).
- **Contador denormalizado `products.sold_count`.** Descartada: se desincroniza en cada reembolso o cancelación y
  hay que mantenerlo desde el módulo de pagos; el agregado con índice es barato y siempre dice la verdad. Si algún
  día el catálogo crece, se podrá materializar con una vista o un job sin cambiar la API.
- **Contar solo sub-órdenes `delivered`.** Descartada: la insignia «más vendido» se muestra en la búsqueda, donde
  lo que interesa es lo que se ha **pagado**; contar solo lo entregado dejaría la insignia sin datos durante días.
- **`sold_count` como faceta u orden de búsqueda** (`sort=best_selling`). No se añade ahora: nadie lo ha pedido
  todavía y sería una opción de API de más que mantener.
- **Listado público reutilizando `/catalog/search`** (cursor y límite 100). Descartada: el buscador ordena y
  filtra para el comprador (relevancia, precio) y no devuelve `updated_at`; un sitemap necesita recorrer **todo**
  el catálogo con `slug` y `lastmod`.
- **Cortar el sitemap por categorías** en lugar de por páginas de cursor. Descartada: obligaría a recorrer el
  árbol de categorías y a repetir el filtro por cada una; el cursor recorre el catálogo entero sin repetir.

## Consecuencias

- La tienda se puede probar y enseñar sin abrir Mailpit (interruptor apagado) y el flujo de verificación sigue
  vivo para el día que se encienda: **una línea del `.env`**, sin reprogramar nada.
- El frontend ya puede: iniciar sesión desde el registro (y fusionar el carrito de invitado en el mismo paso),
  pintar la insignia «más vendido» con unidades reales y construir el `sitemap.xml` recorriendo el catálogo con
  páginas de hasta 500 URLs y `lastmod` real.
- Los apartados 1 y 4 quedan **descartados** por decisión del dueño y anotados como tales en el
  `PENDIENTES-BACKEND.md` del frontend.
