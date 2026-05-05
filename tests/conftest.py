from collections.abc import AsyncIterator

import pytest
from docker.errors import DockerException
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    from tg_bot_aggregator.core.orm import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def postgres_asyncpg_url() -> str:
    container = PostgresContainer("postgres:16-alpine")
    try:
        container.start()
    except DockerException as exc:
        pytest.skip(f"Docker is unavailable for PostgreSQL testcontainers: {exc}")
    try:
        url = make_url(container.get_connection_url())
        yield url.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)
    finally:
        container.stop()
