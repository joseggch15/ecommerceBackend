"""Pruebas unitarias de las plantillas de correo (español, inglés y respaldos)."""

from app.core.config import settings
from app.core.email_templates import (
    EmailTemplate,
    frontend_link,
    humanize_minutes,
    render_email,
    resolve_language,
)

CONTEXT = {
    "full_name": "Juan Pérez",
    "site_name": "marketplace-api",
    "link": "http://localhost:3000/es/verify-email?token=abc",
    "expires": "24 horas",
}


def test_resolve_language_accepts_regions() -> None:
    assert resolve_language("es") == "es"
    assert resolve_language("EN") == "en"
    assert resolve_language("en-US") == "en"
    assert resolve_language("pt-BR") == settings.DEFAULT_LANGUAGE
    assert resolve_language(None) == settings.DEFAULT_LANGUAGE
    assert resolve_language("") == settings.DEFAULT_LANGUAGE


def test_frontend_link_points_to_the_locale_route() -> None:
    link = frontend_link(locale="es", path="verify-email", token="abc/def")
    assert link == f"{settings.FRONTEND_URL}/es/verify-email?token=abc%2Fdef"


def test_humanize_minutes() -> None:
    assert humanize_minutes(1440, language="es") == "24 horas"
    assert humanize_minutes(30, language="es") == "30 minutos"
    assert humanize_minutes(60, language="en") == "1 hour"
    assert humanize_minutes(1, language="en") == "1 minute"


def test_render_verification_email_in_spanish() -> None:
    rendered = render_email(EmailTemplate.EMAIL_VERIFICATION, language="es", **CONTEXT)
    assert "Confirma" in rendered.subject
    assert "Juan Pérez" in rendered.body
    assert CONTEXT["link"] in rendered.body
    assert "24 horas" in rendered.body


def test_render_verification_email_in_english() -> None:
    rendered = render_email(EmailTemplate.EMAIL_VERIFICATION, language="en-US", **CONTEXT)
    assert "Confirm" in rendered.subject
    assert "The link expires in 24 horas" in rendered.body


def test_render_password_reset_email_in_both_languages() -> None:
    spanish = render_email(EmailTemplate.PASSWORD_RESET, language="es", **CONTEXT)
    english = render_email(EmailTemplate.PASSWORD_RESET, language="en", **CONTEXT)

    assert "Restablece" in spanish.subject
    assert "contraseña" in spanish.body
    assert "Reset your password" in english.subject
    assert "password" in english.body
