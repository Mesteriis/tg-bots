from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.models import (
    Bot,
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
