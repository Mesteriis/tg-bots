from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.config import Settings
from tg_bot_aggregator.repositories import (
    BotRepository,
    DestinationRepository,
    SendHistoryRepository,
    TemplateRepository,
)
from tg_bot_aggregator.send_service import (
    IdempotencyConflictError,
    SendService,
    SendServiceError,
)
from tg_bot_aggregator.telegram_bot_api import TelegramBotApiClient


class CapturingEvents:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def publish(self, event_type: str, data: dict[str, Any]) -> str:
        self.events.append(event_type)
        return f"event:{len(self.events)}"


def _bot_api_client(seen: dict[str, Any]) -> TelegramBotApiClient:
    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["json"] = request.read().decode()
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 55}})

    return TelegramBotApiClient(
        "http://telegram-bot-api:8081", httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


async def test_send_text_records_history_and_forum_thread(db_session: AsyncSession) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:token")
    destination = await DestinationRepository(db_session).create(
        bot_id=bot.id, kind="forum_topic", chat_id="-100", message_thread_id=9
    )
    await db_session.commit()
    seen: dict[str, Any] = {}
    events = CapturingEvents()
    service = SendService(db_session, _bot_api_client(seen), Settings(), events)

    row = await service.send_text(bot.id, "hello", destination_id=destination.id, tag="manual")

    assert row.status == "succeeded"
    assert row.telegram_message_id == 55
    assert row.message_thread_id == 9
    assert events.events == ["send.created", "send.succeeded"]
    assert seen["url"].endswith("/sendMessage")


async def test_send_template_uses_template_text(db_session: AsyncSession) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:token")
    await TemplateRepository(db_session).create(tag="deploy", title="Deploy", text="done")
    await db_session.commit()
    service = SendService(db_session, _bot_api_client({}), Settings())

    row = await service.send_template(bot.id, "deploy", chat_id="@ops")

    assert row.text == "done"
    assert row.tag == "deploy"
    assert row.status == "succeeded"


async def test_send_file_requires_local_bot_api(db_session: AsyncSession, tmp_path: Path) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:token")
    await db_session.commit()
    file_path = tmp_path / "a.mp4"
    file_path.write_bytes(b"video")
    settings = Settings(
        TELEGRAM_BOT_API_BASE_URL="https://api.telegram.org",
        SHARED_MEDIA_ROOT=str(tmp_path),
    )
    service = SendService(db_session, _bot_api_client({}), settings)

    with pytest.raises(SendServiceError, match="local"):
        await service.send_file(bot.id, "video", "a.mp4", chat_id="@ops")


async def test_send_file_sends_file_uri(db_session: AsyncSession, tmp_path: Path) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:token")
    await db_session.commit()
    file_path = tmp_path / "a.mp4"
    file_path.write_bytes(b"video")
    seen: dict[str, Any] = {}
    settings = Settings(SHARED_MEDIA_ROOT=str(tmp_path))
    service = SendService(db_session, _bot_api_client(seen), settings)

    row = await service.send_file(bot.id, "video", "a.mp4", chat_id="@ops", caption="cap")

    assert row.status == "succeeded"
    assert row.file_size_bytes == 5
    assert "file://" in seen["json"]
    assert seen["url"].endswith("/sendVideo")


async def test_failed_telegram_response_is_persisted(db_session: AsyncSession) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:token")
    await db_session.commit()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "error_code": 400, "description": "bad"})

    client = TelegramBotApiClient(
        "http://telegram-bot-api:8081", httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    service = SendService(db_session, client, Settings())

    row = await service.send_text(bot.id, "hello", chat_id="@ops")

    assert row.status == "failed"
    assert row.error_code == "400"
    assert row.error_message == "bad"


async def test_send_template_renders_variables(db_session: AsyncSession) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:token")
    await TemplateRepository(db_session).create(
        tag="deploy",
        title="Deploy",
        text="Deploy {{service}}",
    )
    await db_session.commit()
    service = SendService(db_session, _bot_api_client({}), Settings())

    row = await service.send_template(
        bot.id,
        "deploy",
        chat_id="@ops",
        variables={"service": "api"},
    )

    assert row.text == "Deploy api"
    assert row.status == "succeeded"


async def test_send_text_idempotency_key_prevents_duplicate_telegram_calls(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:token")
    await db_session.commit()
    seen: dict[str, Any] = {"count": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["count"] += 1
        return httpx.Response(200, json={"ok": True, "result": {"message_id": seen["count"]}})

    client = TelegramBotApiClient(
        "http://telegram-bot-api:8081", httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    service = SendService(db_session, client, Settings())

    first = await service.send_text(bot.id, "hello", chat_id="@ops", idempotency_key="idem-1")
    second = await service.send_text(bot.id, "hello", chat_id="@ops", idempotency_key="idem-1")

    assert first.id == second.id
    assert second.telegram_message_id == 1
    assert seen["count"] == 1


async def test_send_text_rejects_conflicting_idempotency_key(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:token")
    await db_session.commit()
    service = SendService(db_session, _bot_api_client({}), Settings())

    await service.send_text(bot.id, "hello", chat_id="@ops", idempotency_key="idem-1")

    with pytest.raises(IdempotencyConflictError):
        await service.send_text(bot.id, "changed", chat_id="@ops", idempotency_key="idem-1")


async def test_dry_run_text_validates_without_history_or_telegram_call(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:token")
    destination = await DestinationRepository(db_session).create(
        bot_id=bot.id,
        kind="channel",
        chat_id="@ops",
        alias="ops_channel",
    )
    await db_session.commit()
    seen: dict[str, Any] = {"count": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["count"] += 1
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    service = SendService(
        db_session,
        TelegramBotApiClient(
            "http://telegram-bot-api:8081",
            httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        ),
        Settings(),
    )

    result = await service.dry_run_text(
        bot.id,
        "hello",
        destination_alias="ops_channel",
    )

    assert result["method"] == "sendMessage"
    assert result["destination_id"] == destination.id
    assert result["payload"]["chat_id"] == "@ops"
    assert seen["count"] == 0
    assert await SendHistoryRepository(db_session).list() == []


async def test_queued_send_is_processed_with_transient_retry(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:token")
    await db_session.commit()
    seen: dict[str, Any] = {"count": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["count"] += 1
        if seen["count"] == 1:
            return httpx.Response(
                500,
                json={"ok": False, "error_code": 500, "description": "temporary"},
            )
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 77}})

    client = TelegramBotApiClient(
        "http://telegram-bot-api:8081", httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    service = SendService(
        db_session,
        client,
        Settings(SEND_RETRY_MAX_ATTEMPTS=2, SEND_RETRY_DELAY_SECONDS=0),
    )

    queued = await service.send_text(bot.id, "hello", chat_id="@ops", send_mode="queued")
    assert queued.status == "queued"
    processed = await service.process_queued_send(queued.id)

    assert processed.status == "succeeded"
    assert processed.telegram_message_id == 77
    assert processed.attempt_count == 2
