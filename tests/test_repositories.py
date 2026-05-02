from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.repositories import (
    AnalyticsRepository,
    BotRepository,
    DestinationRepository,
    DiagnosticSettingsRepository,
    SendHistoryRepository,
    TemplateRepository,
)


async def test_repositories_cover_core_crud(db_session: AsyncSession) -> None:
    bots = BotRepository(db_session)
    destinations = DestinationRepository(db_session)
    templates = TemplateRepository(db_session)
    history = SendHistoryRepository(db_session)

    bot = await bots.create(name="ops", token="123:token")
    destination = await destinations.create(bot_id=bot.id, kind="channel", chat_id="@ops")
    template = await templates.create(tag="deploy", title="Deploy", text="done")
    row = await history.create(
        bot_id=bot.id,
        destination_id=destination.id,
        chat_id="@ops",
        tag=template.tag,
        text=template.text,
        media_type="none",
        status="created",
    )
    await history.mark_succeeded(row, telegram_message_id=99, response={"ok": True})
    await db_session.commit()

    assert [item.name for item in await bots.list()] == ["ops"]
    assert (await templates.get_by_tag("deploy")).id == template.id
    assert (await history.list())[0].telegram_message_id == 99

    updated = await bots.update(bot.id, description="primary")
    assert updated.description == "primary"

    assert await destinations.delete(destination.id) is True
    assert await destinations.delete(destination.id) is False


async def test_analytics_repository_creates_runs_and_snapshots(db_session: AsyncSession) -> None:
    analytics = AnalyticsRepository(db_session)

    target = await analytics.create_target(peer_ref="@channel", title="Channel")
    run = await analytics.create_run(target_id=target.id, status="queued", task_id="task-1")
    snapshot = await analytics.create_snapshot(
        target_id=target.id,
        participants_count=None,
        recent_messages_count=2,
        recent_views_total=10,
        recent_forwards_total=None,
        recent_replies_total=None,
        raw_metrics_json={"partial": True},
    )
    await db_session.commit()

    assert (await analytics.list_targets())[0].peer_ref == "@channel"
    assert (await analytics.list_runs())[0].id == run.id
    assert (await analytics.list_snapshots(target_id=target.id))[0].id == snapshot.id


async def test_diagnostic_settings_repository_upserts_singleton(
    db_session: AsyncSession,
) -> None:
    bots = BotRepository(db_session)
    diagnostics = DiagnosticSettingsRepository(db_session)
    bot = await bots.create(name="diag", token="123:token")

    created = await diagnostics.upsert(bot_id=bot.id, is_enabled=True, last_update_id=10)
    updated = await diagnostics.upsert(is_enabled=False, last_error="disabled")
    await db_session.commit()

    loaded = await diagnostics.get()

    assert created.id == 1
    assert updated.id == 1
    assert loaded is not None
    assert loaded.bot_id == bot.id
    assert loaded.is_enabled is False
    assert loaded.last_update_id == 10
    assert loaded.last_error == "disabled"
