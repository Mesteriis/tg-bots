from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import tg_bot_aggregator.domain.operations.database_service as operations_database_service
from tg_bot_aggregator.core.config import Settings
from tg_bot_aggregator.core.db import (
    resolve_runtime_database_state,
    run_migrations,
    to_sync_database_url,
)
from tg_bot_aggregator.core.orm import Base
from tg_bot_aggregator.domain.bots.repository import BotRepository
from tg_bot_aggregator.domain.operations.database_service import migrate_sqlite_to_postgres
from tg_bot_aggregator.domain.operations.repository import RuntimeAdvancedSettingsRepository
from tg_bot_aggregator.infra.uow import UnitOfWork


def test_to_sync_database_url_converts_async_sqlite_and_postgres_urls() -> None:
    assert to_sync_database_url("sqlite+aiosqlite:////tmp/app.db") == "sqlite:////tmp/app.db"
    assert (
        to_sync_database_url("postgresql+asyncpg://user:pass@localhost/app")
        == "postgresql+psycopg://user:pass@localhost/app"
    )


@pytest.mark.asyncio
async def test_resolve_runtime_database_state_switches_to_bootstrap_override(tmp_path) -> None:
    bootstrap_path = tmp_path / "bootstrap.db"
    active_path = tmp_path / "active.db"
    bootstrap_url = f"sqlite+aiosqlite:///{bootstrap_path}"
    active_url = f"sqlite+aiosqlite:///{active_path}"

    bootstrap_engine = create_async_engine(bootstrap_url)
    active_engine = create_async_engine(active_url)
    try:
        async with bootstrap_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with active_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        bootstrap_factory = async_sessionmaker(bootstrap_engine, expire_on_commit=False)
        async with bootstrap_factory() as session:
            await RuntimeAdvancedSettingsRepository(session).upsert(database_url=active_url)
            await session.commit()
    finally:
        await bootstrap_engine.dispose()
        await active_engine.dispose()

    state = await resolve_runtime_database_state(
        Settings(
            DATABASE_URL=bootstrap_url,
            SQLITE_UOW_LOCK_ENABLED=False,
        )
    )
    try:
        assert state.bootstrap_database_url == bootstrap_url
        assert state.active_database_url == active_url
        assert state.uses_bootstrap_database is False
    finally:
        await state.close()


@pytest.mark.asyncio
async def test_resolve_runtime_database_state_switches_to_real_postgres_override(
    postgres_asyncpg_url: str,
    tmp_path,
) -> None:
    bootstrap_path = tmp_path / "bootstrap-real-postgres.db"
    bootstrap_url = f"sqlite+aiosqlite:///{bootstrap_path}"

    bootstrap_engine = create_async_engine(bootstrap_url)
    try:
        async with bootstrap_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        bootstrap_factory = async_sessionmaker(bootstrap_engine, expire_on_commit=False)
        async with bootstrap_factory() as session:
            await RuntimeAdvancedSettingsRepository(session).upsert(
                database_url=postgres_asyncpg_url
            )
            await session.commit()

        await run_migrations(postgres_asyncpg_url)

        state = await resolve_runtime_database_state(
            Settings(
                DATABASE_URL=bootstrap_url,
                SQLITE_UOW_LOCK_ENABLED=False,
            )
        )
        try:
            assert state.bootstrap_database_url == bootstrap_url
            assert state.active_database_url == postgres_asyncpg_url
            assert state.uses_bootstrap_database is False
            async with state.session_factory() as session:
                bots = await BotRepository(session).list()
            assert bots == []
        finally:
            await state.close()
    finally:
        await bootstrap_engine.dispose()


@pytest.mark.asyncio
async def test_migrate_sqlite_to_postgres_uses_snapshot_and_updates_bootstrap_override(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = tmp_path / "source.db"
    target_path = tmp_path / "target.db"
    source_url = f"sqlite+aiosqlite:///{source_path}"
    target_url = "postgresql+asyncpg://example/app"

    source_engine = create_async_engine(source_url)
    target_engine = create_async_engine(f"sqlite+aiosqlite:///{target_path}")
    try:
        async with source_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with target_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        source_factory = async_sessionmaker(source_engine, expire_on_commit=False)
        target_factory = async_sessionmaker(target_engine, expire_on_commit=False)
        async with source_factory() as session:
            await BotRepository(session).create(name="ops", token="123:abc")
            await session.commit()

        async def fake_run_migrations(database_url: str) -> None:
            assert database_url == target_url

        monkeypatch.setattr(operations_database_service, "run_migrations", fake_run_migrations)
        monkeypatch.setattr(
            operations_database_service,
            "is_postgres_database_url",
            lambda database_url: database_url == target_url,
        )
        monkeypatch.setattr(
            operations_database_service,
            "create_engine",
            lambda settings: (
                target_engine if settings.database_url == target_url else source_engine
            ),
        )
        monkeypatch.setattr(
            operations_database_service,
            "create_session_factory",
            lambda engine: target_factory if engine is target_engine else source_factory,
        )

        app = SimpleNamespace(
            state=SimpleNamespace(
                settings=Settings(
                    DATABASE_URL=source_url,
                    SQLITE_UOW_LOCK_ENABLED=False,
                ),
                session_factory=source_factory,
                bootstrap_session_factory=source_factory,
                engine=source_engine,
                bootstrap_engine=source_engine,
                bot_api_client=SimpleNamespace(base_url="http://telegram-bot-api:8081"),
            )
        )
        async with UnitOfWork(
            source_factory,
            settings=Settings(
                DATABASE_URL=source_url,
                SQLITE_UOW_LOCK_ENABLED=False,
            ),
        ) as uow:
            effective = await migrate_sqlite_to_postgres(
                app=app,
                uow=uow,
                target_database_url=target_url,
            )
            await uow.commit()

        async with target_factory() as session:
            bots = await BotRepository(session).list()
            advanced = await RuntimeAdvancedSettingsRepository(session).get()
        async with source_factory() as session:
            bootstrap_advanced = await RuntimeAdvancedSettingsRepository(session).get()

        assert effective.database_url == target_url
        assert len(bots) == 1
        assert bots[0].name == "ops"
        assert advanced is not None
        assert advanced.settings_json["database_url"] == target_url
        assert bootstrap_advanced is not None
        assert bootstrap_advanced.settings_json["database_url"] == target_url
        assert app.state.session_factory is target_factory
        assert app.state.settings.database_url == target_url
    finally:
        await source_engine.dispose()
        await target_engine.dispose()
