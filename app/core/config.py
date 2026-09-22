"""Configuración de la aplicación, cargada desde variables de entorno / .env."""

from decimal import Decimal
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración central de la aplicación (pydantic-settings)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Proyecto
    PROJECT_NAME: str = "marketplace-api"
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    API_V1_PREFIX: str = "/api/v1"

    # Base de datos (PostgreSQL asíncrono)
    DATABASE_URL: str = "postgresql+asyncpg://marketplace:marketplace@localhost:5433/marketplace"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # CORS (orígenes permitidos)
    CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # Seguridad / JWT
    JWT_SECRET_KEY: str = "dev-only-secret-change-me-in-production-000000"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Tokens de verificación / recuperación
    EMAIL_VERIFICATION_EXPIRE_MINUTES: int = 1440  # 24 horas
    PASSWORD_RESET_EXPIRE_MINUTES: int = 30

    # Rate limiting (ventana fija en segundos + máximo por endpoint)
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    RATE_LIMIT_LOGIN_MAX: int = 5
    RATE_LIMIT_REGISTER_MAX: int = 3
    RATE_LIMIT_PASSWORD_RESET_MAX: int = 3

    # Comisión de la plataforma (por defecto global; cada categoría puede sobrescribirla)
    DEFAULT_COMMISSION_RATE: Decimal = Decimal("10.00")

    # Almacenamiento de objetos (MinIO, compatible con S3)
    S3_ENDPOINT_URL: str = "http://localhost:9000"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_BUCKET: str = "marketplace"
    S3_REGION: str = "us-east-1"

    # Monedas y localización
    DEFAULT_CURRENCY: str = "COP"
    DEFAULT_LANGUAGE: str = "es"
    DEFAULT_TIMEZONE: str = "America/Bogota"
    EXCHANGE_RATE_API_URL: str = "https://open.er-api.com/v6/latest"
    EXCHANGE_RATE_API_KEY: str = ""
    EXCHANGE_RATE_CACHE_TTL_SECONDS: int = 3600

    # Pagos (proveedor sandbox por defecto; Mercado Pago es la principal, ver decisión 0019)
    PAYMENT_PROVIDER: str = "sandbox"
    PAYMENT_WEBHOOK_SECRET: str = "dev-webhook-secret"
    PAYMENT_CHECKOUT_BASE_URL: str = "https://sandbox.marketplace.local/checkout"

    # URL pública de esta API: con ella se construye la `notification_url` que el proveedor llama.
    API_PUBLIC_URL: str = "http://localhost:8000"

    # Mercado Pago (Checkout Bricks / Checkout Pro por su API REST).
    # El detalle del protocolo vive en configuración a propósito: cambió entre versiones y
    # **debe confirmarse con su documentación oficial** antes de cobrar de verdad (decisión 0019).
    MERCADOPAGO_ACCESS_TOKEN: str = ""
    MERCADOPAGO_PUBLIC_KEY: str = ""
    MERCADOPAGO_WEBHOOK_SECRET: str = ""
    MERCADOPAGO_API_BASE_URL: str = "https://api.mercadopago.com"
    MERCADOPAGO_SIGNATURE_HEADER: str = "x-signature"
    MERCADOPAGO_REQUEST_ID_HEADER: str = "x-request-id"
    MERCADOPAGO_IDEMPOTENCY_HEADER: str = "X-Idempotency-Key"
    MERCADOPAGO_SIGNATURE_TEMPLATE: str = "id:{data_id};request-id:{request_id};ts:{ts};"
    # "integer" (por defecto): monto sin decimales, como se usa el peso colombiano en la práctica.
    # "decimal": monto con dos decimales.
    MERCADOPAGO_AMOUNT_MODE: str = "integer"

    # Envíos: estimación configurable (ver `app/modules/shipping/estimates.py`). Hoy no hay
    # tarifas por zona ni transportadora integrada: la fecha estimada sale de estos valores y
    # lo declara el campo `source` de la respuesta.
    SHIPPING_ORIGIN_COUNTRY: str = "CO"
    SHIPPING_HANDLING_DAYS: int = 1
    SHIPPING_TRANSIT_DAYS_MIN: int = 2
    SHIPPING_TRANSIT_DAYS_MAX: int = 5
    SHIPPING_INTERNATIONAL_TRANSIT_DAYS_MIN: int = 7
    SHIPPING_INTERNATIONAL_TRANSIT_DAYS_MAX: int = 15
    SHIPPING_FREE: bool = True

    # URL pública del frontend: con ella se construyen los enlaces que van dentro de los correos
    # (`{FRONTEND_URL}/{idioma}/verify-email?token=...`).
    FRONTEND_URL: str = "http://localhost:3000"

    # Notificaciones y correos (remitente: "logging" en desarrollo; "smtp" apunta a Mailpit)
    EMAIL_SENDER: str = "logging"
    EMAIL_FROM: str = "no-reply@marketplace.local"
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1025  # Mailpit escucha aquí en desarrollo (su interfaz web está en 8025)
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    # TLS directo (cifrado desde el principio, típico del puerto 465). Con STARTTLS (587 o el
    # 1025 de Mailpit) se deja en false: la librería lo activa si el servidor lo anuncia.
    SMTP_USE_TLS: bool = False
    # Remitente del sobre SMTP: si está vacío se usa `EMAIL_FROM`.
    SMTP_FROM: str = ""
    SMTP_TIMEOUT_SECONDS: int = 10
    # Worker de correos dentro del proceso de la API (solo para desarrollo: en producción corre
    # aparte). Ver `app/modules/notifications/worker.py`.
    NOTIFICATION_WORKER_ENABLED: bool = False
    NOTIFICATION_WORKER_INTERVAL_SECONDS: float = 5.0

    # Endurecimiento (Fase 13)
    ALLOWED_HOSTS: list[str] = ["*"]
    HSTS_MAX_AGE_SECONDS: int = 31536000


@lru_cache
def get_settings() -> Settings:
    """Devuelve una instancia única (cacheada) de la configuración."""
    return Settings()


settings = get_settings()
