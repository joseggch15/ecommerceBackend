"""Manejo global de errores con formato RFC 9457 (Problem Details).

Cada error incluye un campo "code" estable para que el frontend lo traduzca
al idioma del usuario (los mensajes "detail"/"title" viajan en inglés).
"""

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

logger = get_logger(__name__)


class AppError(Exception):
    """Error de negocio con un `code` estable para que el frontend lo traduzca."""

    def __init__(self, status_code: int, code: str, detail: str) -> None:
        self.status_code = status_code
        self.code = code
        self.detail = detail
        super().__init__(detail)


def _title_for(status_code: int) -> str:
    """Devuelve la frase HTTP estándar para un código, o un valor seguro."""
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Error"


def _code_for_status(status_code: int) -> str:
    """Mapea códigos HTTP comunes a un `code` estable para el frontend."""
    mapping = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        409: "conflict",
        422: "validation_error",
        429: "too_many_requests",
    }
    return mapping.get(status_code, "http_error")


def _problem_detail(
    request: Request,
    status_code: int,
    title: str,
    detail: str,
    code: str,
    *,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    """Construye una respuesta JSON con formato Problem Details (RFC 9457)."""
    request_id = getattr(request.state, "request_id", None)
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": title,
        "status": status_code,
        "detail": detail,
        "code": code,
        "instance": str(request.url.path),
    }
    if request_id is not None:
        body["request_id"] = request_id
    if extra is not None:
        body.update(extra)
    return JSONResponse(status_code=status_code, content=body)


def register_exception_handlers(app: FastAPI) -> None:
    """Registra los manejadores globales de excepciones de la aplicación."""

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return _problem_detail(
            request,
            exc.status_code,
            _title_for(exc.status_code),
            exc.detail,
            exc.code,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        status_code = exc.status_code
        detail = str(exc.detail) if exc.detail else _title_for(status_code)
        return _problem_detail(
            request,
            status_code,
            _title_for(status_code),
            detail,
            _code_for_status(status_code),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _problem_detail(
            request,
            422,
            "Unprocessable Entity",
            "The request failed validation.",
            "validation_error",
            extra={"errors": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error")
        return _problem_detail(
            request,
            500,
            "Internal Server Error",
            "An unexpected error occurred.",
            "internal_error",
        )
