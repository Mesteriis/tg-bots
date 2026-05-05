from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tg_bot_aggregator.core.config import Settings
from tg_bot_aggregator.core.orm import Base
from tg_bot_aggregator.domain.operations.repository import RuntimeAdvancedSettingsRepository
from tg_bot_aggregator.main import create_app


async def test_runtime_settings_patch_migrates_sqlite_to_real_postgres(
    postgres_asyncpg_url: str,
    tmp_path: Path,
) -> None:
    source_database_url = f"sqlite+aiosqlite:///{tmp_path / 'source.db'}"
    source_engine = create_async_engine(source_database_url)
    async with source_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    source_session_factory = async_sessionmaker(source_engine, expire_on_commit=False)
    app = create_app(
        settings=Settings(DATABASE_URL=source_database_url),
        session_factory=source_session_factory,
    )

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            created_template = await client.post(
                "/api/v1/templates",
                json={"tag": "deploy", "title": "Deploy", "text": "v1"},
            )
            assert created_template.status_code == 201

            updated_branch = await client.patch(
                "/api/v1/operations/settings",
                json={"backup_git_branch": "release/e2e"},
            )
            assert updated_branch.status_code == 200

            switched_database = await client.patch(
                "/api/v1/operations/settings",
                json={"database_url": postgres_asyncpg_url},
            )
            assert switched_database.status_code == 200
            switched_payload = switched_database.json()
            assert switched_payload["database_url"] == postgres_asyncpg_url
            assert switched_payload["backup_git_branch"] == "release/e2e"

            loaded_templates = await client.get("/api/v1/templates")
            assert loaded_templates.status_code == 200
            assert [row["tag"] for row in loaded_templates.json()] == ["deploy"]

            loaded_settings = await client.get("/api/v1/operations/settings")
            assert loaded_settings.status_code == 200
            settings_payload = loaded_settings.json()
            assert settings_payload["database_url"] == postgres_asyncpg_url
            assert settings_payload["backup_git_branch"] == "release/e2e"

        async with source_session_factory() as session:
            advanced = await RuntimeAdvancedSettingsRepository(session).get()
            assert advanced is not None
            assert advanced.settings_json["database_url"] == postgres_asyncpg_url
    finally:
        target_engine = getattr(app.state, "engine", None)
        if target_engine is not None:
            await target_engine.dispose()
        await source_engine.dispose()
