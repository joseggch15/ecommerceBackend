"""Utilidades de texto compartidas."""

import re
import unicodedata


def slugify(text: str) -> str:
    """Convierte un texto en un slug apto para URLs.

    Ej.: "Mi Tienda Épica" -> "mi-tienda-epica".
    """
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower().strip()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    return normalized.strip("-") or "item"
