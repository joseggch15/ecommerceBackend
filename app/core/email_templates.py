"""Plantillas de los correos transaccionales, en español e inglés.

Cada plantilla es **texto plano**: es lo que ve cualquier cliente de correo y lo que Mailpit
muestra en su pestaña de texto. El idioma sale del perfil del usuario (`preferred_language`) y, si
no lo tenemos traducido, se usa el idioma por defecto de la plataforma.

Los enlaces apuntan al **frontend** (`FRONTEND_URL`), porque es él quien canjea el token contra la
API; el correo nunca llama a la API directamente.
"""

import enum
from dataclasses import dataclass
from urllib.parse import quote

from app.core.config import settings

# Idiomas con plantilla. Es una tupla (y no el orden de un diccionario) para que el respaldo sea
# explícito y no dependa de cómo se declararon las claves.
SUPPORTED_LANGUAGES: tuple[str, ...] = ("es", "en")
FALLBACK_LANGUAGE = "es"

# Rutas del frontend donde se canjean los tokens (una por tipo de correo).
VERIFY_EMAIL_PATH = "verify-email"
RESET_PASSWORD_PATH = "reset-password"


class EmailTemplate(enum.StrEnum):
    """Tipos de correo con plantilla (los valores coinciden con el `type` de la notificación)."""

    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"


@dataclass(frozen=True)
class RenderedEmail:
    """Correo listo para enviar: asunto y cuerpo en texto plano."""

    subject: str
    body: str


_SUBJECTS: dict[str, dict[EmailTemplate, str]] = {
    "es": {
        EmailTemplate.EMAIL_VERIFICATION: "Confirma tu correo en {site_name}",
        EmailTemplate.PASSWORD_RESET: "Restablece tu contraseña en {site_name}",
    },
    "en": {
        EmailTemplate.EMAIL_VERIFICATION: "Confirm your email at {site_name}",
        EmailTemplate.PASSWORD_RESET: "Reset your password at {site_name}",
    },
}

_BODIES: dict[str, dict[EmailTemplate, str]] = {
    "es": {
        EmailTemplate.EMAIL_VERIFICATION: (
            "Hola {full_name}:\n"
            "\n"
            "Gracias por crear tu cuenta en {site_name}. Confirma tu correo para activarla:\n"
            "\n"
            "{link}\n"
            "\n"
            "El enlace caduca en {expires}. Si no creaste esta cuenta, puedes ignorar este\n"
            "mensaje.\n"
            "\n"
            "Un saludo,\n"
            "El equipo de {site_name}\n"
        ),
        EmailTemplate.PASSWORD_RESET: (
            "Hola {full_name}:\n"
            "\n"
            "Recibimos una solicitud para cambiar la contraseña de tu cuenta en {site_name}.\n"
            "Elige una contraseña nueva aquí:\n"
            "\n"
            "{link}\n"
            "\n"
            "El enlace caduca en {expires} y solo puede usarse una vez. Si no lo pediste tú,\n"
            "ignora este mensaje: tu contraseña actual sigue funcionando.\n"
            "\n"
            "Un saludo,\n"
            "El equipo de {site_name}\n"
        ),
    },
    "en": {
        EmailTemplate.EMAIL_VERIFICATION: (
            "Hello {full_name},\n"
            "\n"
            "Thanks for creating your account at {site_name}. Confirm your email address to\n"
            "activate it:\n"
            "\n"
            "{link}\n"
            "\n"
            "The link expires in {expires}. If you did not create this account, you can ignore\n"
            "this message.\n"
            "\n"
            "Regards,\n"
            "The {site_name} team\n"
        ),
        EmailTemplate.PASSWORD_RESET: (
            "Hello {full_name},\n"
            "\n"
            "We received a request to change the password of your account at {site_name}.\n"
            "Choose a new password here:\n"
            "\n"
            "{link}\n"
            "\n"
            "The link expires in {expires} and can only be used once. If you did not request\n"
            "it, ignore this message: your current password still works.\n"
            "\n"
            "Regards,\n"
            "The {site_name} team\n"
        ),
    },
}

# Duraciones legibles para los correos ("24 horas", "30 minutos" / "24 hours", "30 minutes").
_DURATIONS: dict[str, dict[str, str]] = {
    "es": {
        "hour_one": "1 hora",
        "hours": "{n} horas",
        "minute_one": "1 minuto",
        "minutes": "{n} minutos",
    },
    "en": {
        "hour_one": "1 hour",
        "hours": "{n} hours",
        "minute_one": "1 minute",
        "minutes": "{n} minutes",
    },
}


def resolve_language(language: str | None) -> str:
    """Devuelve el idioma de la plantilla ('es' o 'en') a partir del perfil del usuario.

    Acepta variantes con región (`en-US` -> `en`) y, si no hay traducción, cae al idioma de la
    plataforma y, en último término, al idioma base de respaldo.
    """
    code = (language or "").strip().lower().replace("_", "-")[:2]
    if code in SUPPORTED_LANGUAGES:
        return code

    default = settings.DEFAULT_LANGUAGE.strip().lower()[:2]
    return default if default in SUPPORTED_LANGUAGES else FALLBACK_LANGUAGE


def humanize_minutes(minutes: int, *, language: str) -> str:
    """Duración legible en el idioma dado ('24 horas' si son horas exactas, si no '30 minutos')."""
    units = _DURATIONS[resolve_language(language)]
    if minutes >= 60 and minutes % 60 == 0:
        hours = minutes // 60
        return (units["hour_one"] if hours == 1 else units["hours"]).format(n=hours)
    return (units["minute_one"] if minutes == 1 else units["minutes"]).format(n=minutes)


def frontend_link(*, locale: str, path: str, token: str) -> str:
    """URL del frontend con el token: `{FRONTEND_URL}/{locale}/{path}?token=...`."""
    base = settings.FRONTEND_URL.rstrip("/")
    return f"{base}/{locale}/{path}?token={quote(token, safe='')}"


def render_email(kind: EmailTemplate, *, language: str | None, **context: str) -> RenderedEmail:
    """Renderiza el asunto y el cuerpo de una plantilla en el idioma resuelto.

    `context` son los huecos de la plantilla (`full_name`, `site_name`, `link`, `expires`).
    """
    locale = resolve_language(language)
    return RenderedEmail(
        subject=_SUBJECTS[locale][kind].format(**context),
        body=_BODIES[locale][kind].format(**context),
    )
