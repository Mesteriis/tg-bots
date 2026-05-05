from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config
from anyio import to_thread
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from tg_bot_aggregator.core.config import Settings, get_settings
from tg_bot_aggregator.core.orm import Base
from tg_bot_aggregator.domain.operations.repository import (
    RuntimeAdvancedSettingsRepository,
    RuntimeSettingsRepository,
)
from tg_bot_aggregator.runtime_settings import apply_runtime_settings


@dataclass
class RuntimeDatabaseState:
    bootstrap_settings: Settings
    bootstrap_engine: AsyncEngine
    bootstrap_session_factory: async_sessionmaker[AsyncSession]
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]

    @property
    def bootstrap_database_url(self) -> str:
        return self.bootstrap_settings.database_url

    @property
    def active_database_url(self) -> str:
        return self.settings.database_url

    @property
    def uses_bootstrap_database(self) -> bool:
        return self.engine is self.bootstrap_engine

    async def close(self) -> None:
        if self.engine is not self.bootstrap_engine:
            await self.engine.dispose()
        await self.bootstrap_engine.dispose()


def create_engine(settings: Settings | None = None) -> AsyncEngine:
    resolved = settings or get_settings()
    return create_async_engine(resolved.database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def is_sqlite_database_url(database_url: str) -> bool:
    return make_url(database_url).get_backend_name() == "sqlite"


def is_postgres_database_url(database_url: str) -> bool:
    return make_url(database_url).get_backend_name() == "postgresql"


def is_sqlite_memory_database_url(database_url: str) -> bool:
    if not is_sqlite_database_url(database_url):
        return False
    return database_url.endswith("/:memory:") or database_url.endswith("//:memory:")


def to_sync_database_url(database_url: str) -> str:
    url = make_url(database_url)
    if url.drivername == "sqlite+aiosqlite":
        return url.set(drivername="sqlite").render_as_string(hide_password=False)
    if url.drivername == "postgresql+asyncpg":
        return url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)
    return url.render_as_string(hide_password=False)


async def _maybe_create_sqlite_schema(settings: Settings, engine: AsyncEngine) -> None:
    if not is_sqlite_database_url(settings.database_url):
        return
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def load_effective_settings(
    base_settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> Settings:
    async with session_factory() as session:
        return apply_runtime_settings(
            base_settings,
            await RuntimeSettingsRepository(session).get(),
            await RuntimeAdvancedSettingsRepository(session).get(),
        )


async def resolve_runtime_database_state(
    base_settings: Settings,
    *,
    create_sqlite_schema: bool = False,
) -> RuntimeDatabaseState:
    bootstrap_engine = create_engine(base_settings)
    if create_sqlite_schema:
        await _maybe_create_sqlite_schema(base_settings, bootstrap_engine)
    bootstrap_session_factory = create_session_factory(bootstrap_engine)
    bootstrap_effective_settings = await load_effective_settings(
        base_settings,
        bootstrap_session_factory,
    )
    if bootstrap_effective_settings.database_url == base_settings.database_url:
        return RuntimeDatabaseState(
            bootstrap_settings=base_settings,
            bootstrap_engine=bootstrap_engine,
            bootstrap_session_factory=bootstrap_session_factory,
            settings=bootstrap_effective_settings,
            engine=bootstrap_engine,
            session_factory=bootstrap_session_factory,
        )

    active_engine = create_engine(bootstrap_effective_settings)
    if create_sqlite_schema:
        await _maybe_create_sqlite_schema(bootstrap_effective_settings, active_engine)
    active_session_factory = create_session_factory(active_engine)
    active_effective_settings = await load_effective_settings(
        bootstrap_effective_settings,
        active_session_factory,
    )
    if active_effective_settings.database_url != bootstrap_effective_settings.database_url:
        raise RuntimeError("nested runtime database_url overrides are not supported")
    return RuntimeDatabaseState(
        bootstrap_settings=base_settings,
        bootstrap_engine=bootstrap_engine,
        bootstrap_session_factory=bootstrap_session_factory,
        settings=active_effective_settings,
        engine=active_engine,
        session_factory=active_session_factory,
    )


async def persist_runtime_database_override(
    session_factory: async_sessionmaker[AsyncSession],
    database_url: str,
) -> None:
    async with session_factory() as session:
        await RuntimeAdvancedSettingsRepository(session).upsert(database_url=database_url)
        await session.commit()


def _alembic_config_path() -> Path:
    return Path(__file__).resolve().parents[3] / "alembic.ini"


def _run_alembic_upgrade_sync(database_url: str) -> None:
    config = Config(str(_alembic_config_path()))
    config.attributes["database_url"] = database_url
    config.attributes["target_metadata"] = Base.metadata
    command.upgrade(config, "head")


async def run_migrations(database_url: str) -> None:
    await to_thread.run_sync(_run_alembic_upgrade_sync, database_url)


async def get_session() -> AsyncIterator[AsyncSession]:
    engine = create_engine()
    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        yield session
    await engine.dispose()
