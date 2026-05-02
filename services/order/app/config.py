"""Order Service configuration."""

from functools import lru_cache
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    SERVICE_NAME: str = "order-service"
    SERVICE_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # ── Database ──────────────────────────────────────────────────────────────
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USER: str = "order_user"
    DB_PASSWORD: str = "order_password"
    DB_NAME: str = "order_db"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800

    # ── Inter-service ─────────────────────────────────────────────────────────
    INVENTORY_SERVICE_URL: str = "http://inventory:8000"

    # ── Cache (Redis — for rate limiting) ─────────────────────────────────────
    REDIS_HOST: str = "127.0.0.1"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS: int = 100   # max requests per window per IP
    RATE_LIMIT_WINDOW: int = 60      # window size in seconds

    # ── GCP / Pub/Sub ─────────────────────────────────────────────────────────
    GCP_PROJECT_ID: str = ""
    PUBSUB_EMULATOR_HOST: str = ""
    PUBSUB_TOPIC_ORDER_EVENTS: str = "order-events"
    PUBSUB_SUBSCRIPTION_FULFILLMENT_ASSIGNED: str = "order-fulfillment-assigned-sub"

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

    @property
    def redis_url(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @model_validator(mode="after")
    def _load_secrets(self):
        if not self.DB_PASSWORD:
            try:
                from shared.gcp.secrets import get_secret
                self.DB_PASSWORD = get_secret(
                    "scf-order-db-password", default=self.DB_PASSWORD
                )
            except Exception:
                pass
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
