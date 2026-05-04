from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.repositories import (
    AnalyticsRepository,
    ApiTokenRepository,
    AuditRepository,
    BackupRunRepository,
    BotDiscoveryEventRepository,
    BotDiscoverySettingsRepository,
    BotRepository,
    DestinationRepository,
    DiagnosticSettingsRepository,
    RuntimeSettingsRepository,
    SendBatchRepository,
    SendHistoryRepository,
    SendProfileRepository,
    TemplateRepository,
    TemplateVersionRepository,
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


async def test_ops_repositories_support_scopes_alias_idempotency_audit_and_discovery(
    db_session: AsyncSession,
) -> None:
    bots = BotRepository(db_session)
    tokens = ApiTokenRepository(db_session)
    destinations = DestinationRepository(db_session)
    history = SendHistoryRepository(db_session)
    audit = AuditRepository(db_session)
    discovery_settings = BotDiscoverySettingsRepository(db_session)
    discovery_events = BotDiscoveryEventRepository(db_session)

    bot = await bots.create(name="ops", token="123:token")
    token = await tokens.create(
        name="sender",
        token_hash="hash",
        token_prefix="tga_sender",
        scopes_json=["send"],
    )
    destination = await destinations.create(
        bot_id=bot.id,
        kind="channel",
        chat_id="@ops",
        alias="ops_channel",
    )
    row = await history.create(
        bot_id=bot.id,
        destination_id=destination.id,
        chat_id="@ops",
        text="hello",
        media_type="none",
        status="queued",
        idempotency_key="idem-1",
        idempotency_fingerprint="fingerprint",
        send_mode="queued",
    )
    settings = await discovery_settings.upsert_for_bot(
        bot.id,
        is_enabled=True,
        last_update_id=7,
    )
    event = await discovery_events.create(
        bot_id=bot.id,
        update_id=8,
        chat_id="-100",
        kind="supergroup",
        old_status="left",
        new_status="member",
        raw_update_json={"update_id": 8},
    )
    audit_row = await audit.create(
        source="api",
        action="send.text",
        status="accepted",
        api_token_id=token.id,
        host="tg.sh-inc.ru",
        path="/api/v1/send/text",
        method="POST",
        entity_type="send_history",
        entity_id=str(row.id),
        metadata_json={"idempotency_key": "idem-1"},
    )
    await db_session.commit()

    assert token.scopes_json == ["send"]
    assert (await destinations.get_by_alias(bot.id, "ops_channel")).id == destination.id
    assert (await history.get_by_idempotency_key("idem-1")).id == row.id

    await history.mark_sending(row, attempt_count=2)
    await history.mark_queued(row, task_id="task-1")
    await db_session.commit()

    loaded_settings = await discovery_settings.get_for_bot(bot.id)
    assert row.status == "queued"
    assert row.queued_task_id == "task-1"
    assert row.attempt_count == 2
    assert settings.id == loaded_settings.id
    assert (await discovery_events.list(limit=1))[0].id == event.id
    assert (await audit.list(limit=1))[0].id == audit_row.id


async def test_send_profile_repository_creates_lists_updates_and_deletes(
    db_session: AsyncSession,
) -> None:
    bots = BotRepository(db_session)
    destinations = DestinationRepository(db_session)
    profiles = SendProfileRepository(db_session)

    bot = await bots.create(name="ops", token="123:token")
    destination = await destinations.create(
        bot_id=bot.id,
        kind="channel",
        chat_id="@ops",
        alias="ops_channel",
    )
    profile = await profiles.create(
        name="Deploy",
        bot_id=bot.id,
        send_kind="template",
        destination_id=destination.id,
        template_tag="deploy",
        variables_json={"service": "api"},
        is_active=True,
    )
    await db_session.commit()

    listed = await profiles.list()
    updated = await profiles.update(profile.id, name="Deploy prod", destination_alias="prod")
    await db_session.commit()

    assert listed[0].id == profile.id
    assert listed[0].variables_json == {"service": "api"}
    assert updated.name == "Deploy prod"
    assert updated.destination_alias == "prod"
    assert await profiles.delete(profile.id) is True
    assert await profiles.delete(profile.id) is False


async def test_send_batch_repository_creates_batch_and_items(
    db_session: AsyncSession,
) -> None:
    bots = BotRepository(db_session)
    destinations = DestinationRepository(db_session)
    batches = SendBatchRepository(db_session)

    bot = await bots.create(name="ops", token="123:token")
    first = await destinations.create(bot_id=bot.id, kind="channel", chat_id="@one")
    second = await destinations.create(bot_id=bot.id, kind="channel", chat_id="@two")
    batch = await batches.create_batch(
        name="Release",
        bot_id=bot.id,
        send_kind="text",
        text="hello",
    )
    await batches.add_item(batch.id, destination_id=first.id, chat_id="@one")
    await batches.add_item(batch.id, destination_id=second.id, chat_id="@two")
    await db_session.commit()

    loaded = await batches.get_batch(batch.id)
    items = await batches.list_items(batch.id)
    await batches.mark_batch_status(batch, "queued")
    await batches.mark_item_status(items[0], "queued", send_history_id=10)
    await db_session.commit()

    assert loaded is not None
    assert loaded.name == "Release"
    assert [item.chat_id for item in items] == ["@one", "@two"]
    assert batch.status == "queued"
    assert items[0].send_history_id == 10


async def test_runtime_settings_and_backup_run_repositories(db_session: AsyncSession) -> None:
    settings_repo = RuntimeSettingsRepository(db_session)
    backup_runs = BackupRunRepository(db_session)

    settings = await settings_repo.get_or_create()
    updated = await settings_repo.upsert(max_local_file_bytes=123, backup_git_repo_url="file:///tmp/x")
    run = await backup_runs.create(
        status="succeeded",
        items_exported=2,
        backup_json={"bots": [], "templates": []},
    )
    await db_session.commit()

    assert settings.id == 1
    assert updated.max_local_file_bytes == 123
    assert updated.backup_git_repo_url == "file:///tmp/x"
    assert (await backup_runs.list())[0].id == run.id


async def test_template_version_repository_creates_ordered_versions(
    db_session: AsyncSession,
) -> None:
    templates = TemplateRepository(db_session)
    versions = TemplateVersionRepository(db_session)
    template = await templates.create(tag="deploy", title="Deploy", text="v1")
    first = await versions.create_from_template(template)
    template.text = "v2"
    second = await versions.create_from_template(template)
    await db_session.commit()

    listed = await versions.list_for_template(template.id)

    assert [row.id for row in listed] == [first.id, second.id]
    assert [row.version_number for row in listed] == [1, 2]
    assert listed[0].text == "v1"
    assert listed[1].text == "v2"
