"""Cliente de almacenamiento de objetos (S3/MinIO) con URLs prefirmadas."""

import uuid

import boto3  # type: ignore[import-untyped]  # boto3 no distribuye stubs de tipos
from botocore.client import Config  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from app.core.config import settings

_s3_client = boto3.client(
    "s3",
    endpoint_url=settings.S3_ENDPOINT_URL,
    aws_access_key_id=settings.S3_ACCESS_KEY,
    aws_secret_access_key=settings.S3_SECRET_KEY,
    region_name=settings.S3_REGION,
    config=Config(signature_version="s3v4"),
)


def ensure_bucket() -> None:
    """Crea el bucket de la aplicación si aún no existe (idempotente)."""
    try:
        _s3_client.head_bucket(Bucket=settings.S3_BUCKET)
    except ClientError:
        _s3_client.create_bucket(Bucket=settings.S3_BUCKET)


def generate_presigned_upload_url(object_key: str, content_type: str | None = None) -> str:
    """Devuelve una URL prefirmada para subir un objeto con PUT (válida 1 hora)."""
    params: dict[str, str] = {"Bucket": settings.S3_BUCKET, "Key": object_key}
    if content_type is not None:
        params["ContentType"] = content_type
    return str(_s3_client.generate_presigned_url("put_object", Params=params, ExpiresIn=3600))


def new_object_key(extension: str = "", prefix: str = "products") -> str:
    """Genera una clave de objeto única dentro del bucket.

    La extensión se normaliza **con el punto delante** (`products/<32 hex>.jpg`): el proxy de
    medios del frontend valida las claves con una lista blanca que exige la extensión tras el
    punto, así que sin él todas las imágenes reales se rechazan (apartado 8 de los pendientes).

    El prefijo se parametriza porque los logos de tienda viven en `stores/` y los productos en
    `products/` (antes todo se guardaba bajo `products/`, incluso los logos).
    """
    clean_prefix = prefix.strip().strip("/").lower() or "products"
    clean_extension = extension.strip().lower()
    if clean_extension and not clean_extension.startswith("."):
        clean_extension = f".{clean_extension}"

    return f"{clean_prefix}/{uuid.uuid4().hex}{clean_extension}"
