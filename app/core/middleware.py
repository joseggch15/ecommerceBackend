"""Middlewares de la aplicación."""

import uuid

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestContextMiddleware:
    """Middleware ASGI puro: asigna un request_id a cada petición HTTP.

    El request_id se guarda en ``request.state`` (para los manejadores de error),
    se agrega al contexto de logging (structlog) y se devuelve en el header
    ``X-Request-ID`` de la respuesta.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        raw_headers = dict(scope.get("headers", []))
        request_id = raw_headers.get(b"x-request-id", b"").decode("latin-1") or str(uuid.uuid4())

        scope.setdefault("state", {})
        scope["state"]["request_id"] = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            structlog.contextvars.clear_contextvars()


def _security_headers(hsts_max_age: int | None) -> list[tuple[bytes, bytes]]:
    """Cabeceras de seguridad para respuestas de la API."""
    headers: list[tuple[bytes, bytes]] = [
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"no-referrer"),
        (b"permissions-policy", b"geolocation=(), microphone=(), camera=()"),
        # La API solo devuelve JSON: no necesita cargar nada.
        (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
        (b"cross-origin-resource-policy", b"same-site"),
    ]
    if hsts_max_age:
        headers.append(
            (
                b"strict-transport-security",
                f"max-age={hsts_max_age}; includeSubDomains".encode(),
            )
        )
    return headers


class SecurityHeadersMiddleware:
    """Añade cabeceras de seguridad a todas las respuestas HTTP.

    HSTS se activa solo si se pasa `hsts_max_age` (producción), para no dejar
    el navegador forzando HTTPS en desarrollo sobre `http://localhost`.
    """

    def __init__(self, app: ASGIApp, *, hsts_max_age: int | None = None) -> None:
        self.app = app
        self.hsts_max_age = hsts_max_age

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(_security_headers(self.hsts_max_age))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_security_headers)
