"""Fulfillment Service configuration."""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    SERVICE_NAME: str = "fulfillment-service"
    SERVICE_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # ── Database ──────────────────────────────────────────────────────────────
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USER: str = "fulfillment_user"
    DB_PASSWORD: str = "fulfillment_password"
    DB_NAME: str = "fulfillment_db"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800

    # ── Inter-service ─────────────────────────────────────────────────────────
    ORDER_SERVICE_URL: str = "http://order:8001"

    # ── GCP / Pub/Sub ─────────────────────────────────────────────────────────
    GCP_PROJECT_ID: str = ""
    PUBSUB_EMULATOR_HOST: str = ""
    PUBSUB_TOPIC_FULFILLMENT_EVENTS: str = "fulfillment-events"
    PUBSUB_SUBSCRIPTION_ORDER_CREATED: str = "fulfillment-order-created-sub"

    @property
    def database_url(self) -> str:
        return (
            f"mysql+aiomysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"
        )

    @property
    def sync_database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
