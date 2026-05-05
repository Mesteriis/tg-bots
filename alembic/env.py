from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, text
from sqlalchemy.engine import Connection

from alembic import context
from tg_bot_aggregator.core.config import get_settings
from tg_bot_aggregator.core.db import to_sync_database_url
from tg_bot_aggregator.core.orm import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = config.attributes.get("target_metadata", Base.metadata)
ALEMBIC_VERSION_LENGTH = 128


def _database_url() -> str:
    configured = config.attributes.get("database_url")
    if isinstance(configured, str) and configured:
        return configured
    return get_settings().database_url


def _ensure_postgres_version_table_capacity(connection: Connection) -> None:
    if connection.dialect.name != "postgresql":
        return
    connection.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS alembic_version (
                version_num VARCHAR({ALEMBIC_VERSION_LENGTH}) NOT NULL PRIMARY KEY
            )
            """
        )
    )
    connection.execute(
        text(
            f"""
            ALTER TABLE alembic_version
            ALTER COLUMN version_num TYPE VARCHAR({ALEMBIC_VERSION_LENGTH})
            """
        )
    )


def run_migrations_offline() -> None:
    context.configure(
        url=to_sync_database_url(_database_url()),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = to_sync_database_url(_database_url())
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.begin() as connection:
        _ensure_postgres_version_table_capacity(connection)
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
