from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.models import Bot, Destination, MessageTemplate, SendHistory


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
