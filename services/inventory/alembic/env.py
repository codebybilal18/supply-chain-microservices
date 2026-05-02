"""
Alembic migration environment.

Uses a synchronous connection to MySQL (PyMySQL) because Alembic's default
runner is synchronous.  The URL is pulled from the same pydantic Settings
object as the application, ensuring migrations always target the correct DB.

To create a new migration:
  alembic revision --autogenerate -m "describe change"

To apply all pending migrations:
  alembic upgrade head

To roll back one step:
  alembic downgrade -1
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import all models so Alembic's autogenerate can detect schema changes.
# The __init__.py re-exports every model class.
import app.models  # noqa: F401
from app.config import settings
from app.database import Base

# ── Alembic Config object ─────────────────────────────────────────────────────
config = context.config

# Override sqlalchemy.url with the value from pydantic Settings
config.set_main_option("sqlalchemy.url", settings.sync_database_url)

# Set up Python logging from the alembic.ini [loggers] section
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The target metadata for autogenerate
target_metadata = Base.metadata


# ── Migration runners ─────────────────────────────────────────────────────────

def run_migrations_offline() -> None:
    """
    Run migrations without a live DB connection (emit SQL to stdout).
    Useful for generating SQL scripts for DBA review.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # no pooling — migrations are short-lived
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,   # detect column type changes
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
