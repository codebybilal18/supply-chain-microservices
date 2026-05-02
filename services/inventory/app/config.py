"""
Application configuration — loaded once at startup from environment variables.

Design decisions:
  - pydantic-settings validates types at import time; bad config = fast fail.
  - All secrets come from env vars (never hardcoded defaults in production).
  - `.env` files are supported for local development convenience.
"""

from functools import lru_cache
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",           # ignore unknown env vars (forward-compat)
    )

    # ── Service Identity ───────────────────────────────────────────────────────
    SERVICE_NAME: str = "inventory-service"
    SERVICE_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # ── Database ──────────────────────────────────────────────────────────────
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USER: str = "inventory_user"
    DB_PASSWORD: str = "inventory_password"
    DB_NAME: str = "inventory_db"

    # Connection pool — sized for Cloud Run: 1 container × 10 connections.
    # Cloud SQL default max_connections = 100; leave headroom for other services.
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800   # recycle connections after 30 min (avoids "gone away")

    # ── Cache (Redis — wired in Phase 2) ──────────────────────────────────────
    REDIS_HOST: str = "127.0.0.1"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS: int = 200   # max requests per window per IP
    RATE_LIMIT_WINDOW: int = 60      # window size in seconds

    # ── GCP (wired in Phase 4) ────────────────────────────────────────────────
    GCP_PROJECT_ID: str = ""
    PUBSUB_EMULATOR_HOST: str = ""

    # ── Pub/Sub topics & subscriptions ───────────────────────────────────────
    PUBSUB_TOPIC_INVENTORY_EVENTS: str = "inventory-events"
    PUBSUB_SUBSCRIPTION_ORDER_CREATED: str = "inventory-order-created-sub"
    PUBSUB_SUBSCRIPTION_FULFILLMENT_COMPLETED: str = "inventory-fulfillment-completed-sub"

    # ── Derived properties ────────────────────────────────────────────────────

    @property
    def database_url(self) -> str:
        """Async MySQL URL for SQLAlchemy (aiomysql driver)."""
        return (
            f"mysql+aiomysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            "?charset=utf8mb4"
        )

    @property
    def sync_database_url(self) -> str:
        """Sync MySQL URL used by Alembic migrations (PyMySQL driver)."""
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            "?charset=utf8mb4"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @field_validator("DB_POOL_SIZE", "DB_MAX_OVERFLOW", mode="before")
    @classmethod
    def must_be_positive(cls, v: int) -> int:
        if int(v) <= 0:
            raise ValueError("Pool size must be > 0")
        return int(v)

    @model_validator(mode="after")
    def _load_secrets(self):
        """Pull DB_PASSWORD from Secret Manager when running on GCP."""
        if not self.DB_PASSWORD:
            try:
                from shared.gcp.secrets import get_secret
                self.DB_PASSWORD = get_secret(
                    "scf-inventory-db-password", default=self.DB_PASSWORD
                )
            except Exception:
                pass
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance (singleton)."""
    return Settings()


# Module-level singleton — import this everywhere.
settings = get_settings()
