from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.models import (
    ApiToken,
    AuditEvent,
    Bot,
    BotDiscoveryEvent,
    BotDiscoverySettings,
    Destination,
    DiagnosticBotSettings,
    MessageTemplate,
    SendHistory,
)


async def test_core_models_can_be_inserted(db_session: AsyncSession) -> None:
    bot = Bot(name="ops", token="123:token", username="ops_bot", telegram_bot_id=123)
    db_session.add(bot)
    await db_session.flush()

    destination = Destination(
        bot_id=bot.id,
        kind="forum_topic",
        chat_id="-100123",
        message_thread_id=42,
        title="Deployments",
    )
    template = MessageTemplate(tag="deploy", title="Deploy", text="Deployment done")
    db_session.add_all([destination, template])
    await db_session.flush()

    history = SendHistory(
        bot_id=bot.id,
        destination_id=destination.id,
        chat_id=destination.chat_id,
        message_thread_id=destination.message_thread_id,
        tag=template.tag,
        text=template.text,
        media_type="none",
        status="succeeded",
        telegram_message_id=77,
    )
    db_session.add(history)
    await db_session.commit()

    rows = (await db_session.execute(select(SendHistory))).scalars().all()

    assert len(rows) == 1
    assert rows[0].chat_id == "-100123"
    assert rows[0].message_thread_id == 42


async def test_diagnostic_settings_model_can_select_product_bot(
    db_session: AsyncSession,
) -> None:
    bot = Bot(name="diagnostics", token="123:token", username="diag_bot", telegram_bot_id=123)
    db_session.add(bot)
    await db_session.flush()

    settings = DiagnosticBotSettings(id=1, bot_id=bot.id, is_enabled=True, last_update_id=77)
    db_session.add(settings)
    await db_session.commit()

    row = (await db_session.execute(select(DiagnosticBotSettings))).scalar_one()

    assert row.bot_id == bot.id
    assert row.is_enabled is True
    assert row.last_update_id == 77


async def test_ops_automation_models_can_be_inserted(db_session: AsyncSession) -> None:
    bot = Bot(name="ops", token="123:token", username="ops_bot", telegram_bot_id=123)
    db_session.add(bot)
    await db_session.flush()

    token = ApiToken(
        name="sender",
        token_hash="hash",
        token_prefix="tga_sender",
        scopes_json=["read", "send"],
    )
    destination = Destination(
        bot_id=bot.id,
        kind="channel",
        chat_id="@ops",
        title="Ops",
        alias="ops_channel",
    )
    history = SendHistory(
        bot_id=bot.id,
        destination_id=None,
        chat_id="@ops",
        text="hello",
        media_type="none",
        status="queued",
        send_mode="queued",
        idempotency_key="send-1",
        idempotency_fingerprint="fingerprint",
        attempt_count=1,
    )
    audit = AuditEvent(
        source="api",
        action="send.text",
        status="accepted",
        api_token_id=None,
        host="127.0.0.1",
        path="/api/v1/send/text",
        method="POST",
        entity_type="send_history",
        entity_id="1",
        metadata_json={"redacted": True},
    )
    discovery_settings = BotDiscoverySettings(
        bot_id=bot.id,
        is_enabled=True,
        last_update_id=11,
    )
    db_session.add_all([token, destination, history, audit, discovery_settings])
    await db_session.flush()
    discovery_event = BotDiscoveryEvent(
        bot_id=bot.id,
        update_id=12,
        chat_id="-100",
        kind="supergroup",
        old_status="left",
        new_status="administrator",
        raw_update_json={"update_id": 12},
    )
    db_session.add(discovery_event)
    await db_session.commit()

    loaded_destination = (await db_session.execute(select(Destination))).scalars().first()
    loaded_token = (await db_session.execute(select(ApiToken))).scalar_one()
    loaded_history = (await db_session.execute(select(SendHistory))).scalars().first()
    loaded_audit = (await db_session.execute(select(AuditEvent))).scalar_one()
    loaded_discovery = (await db_session.execute(select(BotDiscoverySettings))).scalar_one()

    assert loaded_destination.alias == "ops_channel"
    assert loaded_token.scopes_json == ["read", "send"]
    assert loaded_history.send_mode == "queued"
    assert loaded_history.idempotency_key == "send-1"
    assert loaded_audit.action == "send.text"
    assert loaded_discovery.last_update_id == 11
