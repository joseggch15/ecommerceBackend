"""Configuración de la aplicación, cargada desde variables de entorno / .env."""

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


@lru_cache
def get_settings() -> Settings:
    """Devuelve una instancia única (cacheada) de la configuración."""
    return Settings()


settings = get_settings()
