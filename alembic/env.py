"""
alembic/env.py — Alembic runtime environment.

Reads the database URL from bot.config.settings (which reads from .env)
so that migrations always target the same DB as the running application.

Usage:
    alembic upgrade head      # apply all migrations
    alembic revision --autogenerate -m "add column"  # generate new migration
    alembic downgrade -1      # roll back one step
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# ---------------------------------------------------------------------------
# Import project models so Alembic can detect schema changes automatically
# ---------------------------------------------------------------------------
from bot.config import settings
from bot.database.models import Base  # noqa: F401 — needed for target_metadata

# ---------------------------------------------------------------------------
# Alembic Config object — provides access to the values in alembic.ini
# ---------------------------------------------------------------------------
config = context.config

# Override the sqlalchemy.url in alembic.ini with the value from our settings.
# This means the same .env file controls both the running bot AND migrations.
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Set up Python logging using the config in alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata object for 'autogenerate' support
target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Offline mode — generate SQL script without a live DB connection
# ---------------------------------------------------------------------------

def run_migrations_offline() -> None:
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


# ---------------------------------------------------------------------------
# Online mode — run migrations against a live DB connection
# ---------------------------------------------------------------------------

def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
