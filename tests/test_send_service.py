import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.core.config import Settings
from tg_bot_aggregator.core.time import utc_now
from tg_bot_aggregator.domain.batches.repository import SendBatchRepository
from tg_bot_aggregator.domain.batches.service import WorkflowService
from tg_bot_aggregator.domain.bots.repository import BotRepository
from tg_bot_aggregator.domain.destinations.repository import DestinationRepository
from tg_bot_aggregator.domain.reliability.service import MemoryRateLimitStore, SendRateLimiter
from tg_bot_aggregator.domain.sending.repository import (
    SendAttemptRepository,
    SendHistoryRepository,
)
from tg_bot_aggregator.domain.sending.service import (
    IdempotencyConflictError,
    SendService,
    SendServiceError,
)
from tg_bot_aggregator.domain.templates.repository import TemplateRepository
from tg_bot_aggregator.infra.telegram_client import TelegramBotApiClient, TelegramBotApiError


class CapturingEvents:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def publish(self, event_type: str, data: dict[str, Any]) -> str:
        self.events.append(event_type)
        return f"event:{len(self.events)}"


class CapturingCallbacks:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    async def publish(self, url: str, payload: dict[str, Any]) -> None:
        self.payloads.append({"url": url, "payload": payload})


class FailingEvents:
    async def publish(self, event_type: str, data: dict[str, Any]) -> str:
        raise RuntimeError("event bus is unavailable")


class CancellingLockedEvents:
    async def publish(self, event_type: str, data: dict[str, Any]) -> str:
        if event_type == "send.locked":
            raise asyncio.CancelledError()
        return f"event:{event_type}"


def _bot_api_client(
    seen: dict[str, Any],
    *,
    error: TelegramBotApiError | None = None,
) -> TelegramBotApiClient:
    async def handler(request: httpx.Request) -> httpx.Response:
        if error is not None:
            raise error
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
    settings = Settings(
        TELEGRAM_BOT_API_BASE_URL="http://telegram-bot-api:8081",
        SHARED_MEDIA_ROOT=str(tmp_path),
    )
    service = SendService(db_session, _bot_api_client(seen), settings)

    row = await service.send_file(bot.id, "video", "a.mp4", chat_id="@ops", caption="cap")

    assert row.status == "succeeded"
    assert row.file_size_bytes == 5
    assert "file://" in seen["json"]
    assert seen["url"].endswith("/sendVideo")


async def test_send_file_rejects_unavailable_shared_media_root_before_telegram_call(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:token")
    await db_session.commit()
    seen: dict[str, Any] = {}
    settings = Settings(
        TELEGRAM_BOT_API_BASE_URL="http://telegram-bot-api:8081",
        SHARED_MEDIA_ROOT=str(tmp_path / "missing-media"),
    )
    service = SendService(db_session, _bot_api_client(seen), settings)

    with pytest.raises(SendServiceError, match="shared media root is not available"):
        await service.send_file(bot.id, "video", "a.mp4", chat_id="@ops")

    assert seen == {}


async def test_send_file_can_require_shared_media_root_to_be_mounted(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:token")
    await db_session.commit()
    (tmp_path / "a.mp4").write_bytes(b"video")
    seen: dict[str, Any] = {}
    settings = Settings(
        TELEGRAM_BOT_API_BASE_URL="http://telegram-bot-api:8081",
        SHARED_MEDIA_ROOT=str(tmp_path),
        SHARED_MEDIA_REQUIRE_MOUNT=True,
    )
    service = SendService(db_session, _bot_api_client(seen), settings)

    with pytest.raises(SendServiceError, match="shared media root is not mounted"):
        await service.send_file(bot.id, "video", "a.mp4", chat_id="@ops")

    assert seen == {}


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


async def test_workflow_preview_send_delegates_without_history_or_telegram_call(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:token")
    destination = await DestinationRepository(db_session).create(
        bot_id=bot.id,
        kind="channel",
        chat_id="@ops",
        alias="ops_channel",
    )
    await TemplateRepository(db_session).create(
        tag="deploy",
        title="Deploy",
        text="Deploy {{service}}",
    )
    await db_session.commit()
    seen: dict[str, Any] = {"count": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["count"] += 1
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    workflow = WorkflowService(
        SendService(
            db_session,
            TelegramBotApiClient(
                "http://telegram-bot-api:8081",
                httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            ),
            Settings(),
        )
    )

    preview = await workflow.preview_send(
        kind="template",
        bot_id=bot.id,
        destination_id=destination.id,
        tag="deploy",
        variables={"service": "api"},
    )

    assert preview["kind"] == "template"
    assert preview["method"] == "sendMessage"
    assert preview["payload"]["text"] == "Deploy api"
    assert preview["destination_id"] == destination.id
    assert seen["count"] == 0
    assert await SendHistoryRepository(db_session).list() == []


async def test_retry_failed_history_row_resends_existing_payload(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:token")
    await db_session.commit()

    async def failing_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"ok": False, "error_code": 500, "description": "boom"})

    first_service = SendService(
        db_session,
        TelegramBotApiClient(
            "http://telegram-bot-api:8081",
            httpx.AsyncClient(transport=httpx.MockTransport(failing_handler)),
        ),
        Settings(),
    )
    failed = await first_service.send_text(bot.id, "hello", chat_id="@ops")
    seen: dict[str, Any] = {"count": 0}

    async def success_handler(request: httpx.Request) -> httpx.Response:
        seen["count"] += 1
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 77}})

    retry_service = SendService(
        db_session,
        TelegramBotApiClient(
            "http://telegram-bot-api:8081",
            httpx.AsyncClient(transport=httpx.MockTransport(success_handler)),
        ),
        Settings(),
    )

    retried = await retry_service.retry_history(failed.id)

    assert failed.status == "queued"
    assert retried.id == failed.id
    assert retried.status == "queued"
    assert retried.error_code is None
    assert retried.error_message is None
    assert seen["count"] == 0


async def test_cancelled_queued_history_row_is_not_processed(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:token")
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
    queued = await service.send_text(bot.id, "hello", chat_id="@ops", send_mode="queued")

    cancelled = await service.cancel_history(queued.id)
    processed = await service.process_queued_send(queued.id)

    assert cancelled.status == "cancelled"
    assert processed.status == "cancelled"
    assert seen["count"] == 0


async def test_workflow_batch_preview_and_enqueue_create_history_rows(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:token")
    first = await DestinationRepository(db_session).create(
        bot_id=bot.id,
        kind="channel",
        chat_id="@one",
    )
    second = await DestinationRepository(db_session).create(
        bot_id=bot.id,
        kind="channel",
        chat_id="@two",
    )
    batches = SendBatchRepository(db_session)
    batch = await batches.create_batch(
        name="Release",
        bot_id=bot.id,
        send_kind="text",
        text="hello",
    )
    await batches.add_item(batch.id, destination_id=first.id, chat_id="@one")
    await batches.add_item(batch.id, destination_id=second.id, chat_id="@two")
    await db_session.commit()
    seen: dict[str, Any] = {"count": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["count"] += 1
        return httpx.Response(200, json={"ok": True, "result": {"message_id": seen["count"]}})

    workflow = WorkflowService(
        SendService(
            db_session,
            TelegramBotApiClient(
                "http://telegram-bot-api:8081",
                httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            ),
            Settings(),
        )
    )

    preview = await workflow.preview_batch(batch.id)
    enqueued = await workflow.enqueue_batch(batch.id)

    items = await batches.list_items(batch.id)
    history = await SendHistoryRepository(db_session).list()

    assert [item["payload"]["chat_id"] for item in preview["previews"]] == ["@one", "@two"]
    assert enqueued.status == "queued"
    assert [item.status for item in items] == ["queued", "queued"]
    assert len(history) == 2
    assert {row.status for row in history} == {"queued"}
    assert seen["count"] == 0


async def test_workflow_batch_cancel_only_pending_or_queued_items(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:token")
    batches = SendBatchRepository(db_session)
    batch = await batches.create_batch(
        name="Release",
        bot_id=bot.id,
        send_kind="text",
        text="hello",
    )
    first = await batches.add_item(batch.id, chat_id="@one")
    second = await batches.add_item(batch.id, chat_id="@two")
    await batches.mark_item_status(second, "succeeded", send_history_id=100)
    await db_session.commit()
    workflow = WorkflowService(SendService(db_session, _bot_api_client({}), Settings()))

    cancelled = await workflow.cancel_batch(batch.id)
    items = await batches.list_items(batch.id)

    assert cancelled.status == "cancelled"
    assert [(item.id, item.status) for item in items] == [
        (first.id, "cancelled"),
        (second.id, "succeeded"),
    ]


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
    first_pass = await service.process_queued_send(queued.id, worker_id="worker-a")

    assert first_pass.status == "deferred"
    assert first_pass.telegram_message_id is None
    assert first_pass.attempt_count == 1
    assert seen["count"] == 1

    first_pass.next_retry_at = None
    await db_session.commit()
    second_pass = await service.process_queued_send(queued.id, worker_id="worker-a")

    assert second_pass.status == "succeeded"
    assert second_pass.telegram_message_id == 77
    assert second_pass.attempt_count == 2
    assert seen["count"] == 2


async def test_queued_send_rate_limit_error_is_deferred_with_attempt(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:token")
    await db_session.commit()
    client = _bot_api_client(
        {},
        error=TelegramBotApiError(
            method="sendMessage",
            error_code=429,
            description="Too Many Requests",
            payload={"ok": False, "parameters": {"retry_after": 9}, "token": "123:token"},
        ),
    )
    service = SendService(
        db_session,
        client,
        Settings(reliability_enabled=True, send_retry_max_attempts=3),
    )
    row = await service.send_text(bot.id, "hello", chat_id="@ops", send_mode="queued")

    processed = await service.process_queued_send(row.id, worker_id="worker-a")
    attempts = await SendAttemptRepository(db_session).list_for_send(row.id)

    assert processed.status == "deferred"
    assert processed.retry_after_seconds == 9
    assert processed.next_retry_at is not None
    assert processed.locked_by is None
    assert attempts[0].attempt_number == 1
    assert attempts[0].worker_id == "worker-a"
    assert attempts[0].status == "deferred"
    assert attempts[0].error_kind == "telegram_rate_limit"
    assert attempts[0].response_payload_json == {
        "ok": False,
        "parameters": {"retry_after": 9},
        "token": "[REDACTED]",
    }


async def test_exhausted_retry_budget_moves_to_dead_letter(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:token")
    await db_session.commit()
    client = _bot_api_client(
        {},
        error=TelegramBotApiError(
            method="sendMessage",
            error_code=502,
            description="Bad Gateway",
            payload={"ok": False},
        ),
    )
    service = SendService(
        db_session,
        client,
        Settings(reliability_enabled=True, send_retry_max_attempts=1),
    )
    row = await service.send_text(bot.id, "hello", chat_id="@ops", send_mode="queued")

    processed = await service.process_queued_send(row.id, worker_id="worker-a")
    attempts = await SendAttemptRepository(db_session).list_for_send(row.id)

    assert processed.status == "dead_letter"
    assert processed.last_error_kind == "telegram_server"
    assert processed.locked_by is None
    assert attempts[0].status == "dead_letter"
    assert attempts[0].error_kind == "telegram_server"


async def test_non_retryable_client_error_moves_to_blocked_with_callback(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:token")
    await db_session.commit()
    callbacks = CapturingCallbacks()
    events = CapturingEvents()
    client = _bot_api_client(
        {},
        error=TelegramBotApiError(
            method="sendMessage",
            error_code=400,
            description="Bad Request",
            payload={"ok": False},
        ),
    )
    service = SendService(
        db_session,
        client,
        Settings(
            reliability_enabled=True,
            callback_enabled=True,
            callback_url="http://callbacks.local/send",
        ),
        events,
        callbacks,
    )
    row = await service.send_text(bot.id, "hello", chat_id="@ops", send_mode="queued")

    processed = await service.process_queued_send(row.id, worker_id="worker-a")
    attempts = await SendAttemptRepository(db_session).list_for_send(row.id)

    assert processed.status == "blocked"
    assert processed.last_error_kind == "telegram_client"
    assert attempts[0].status == "blocked"
    assert "send.blocked" in events.events
    assert callbacks.payloads[0]["payload"]["event_type"] == "send.blocked"


async def test_retry_history_requeues_dead_letter_blocked_and_failed(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:token")
    history = SendHistoryRepository(db_session)
    rows = [
        await history.create(
            bot_id=bot.id,
            chat_id=f"@ops_{status}",
            media_type="none",
            status=status,
            send_mode="queued",
            attempt_count=2,
            error_code="500",
            error_message="boom",
            last_error_kind="telegram_server",
            retry_after_seconds=30,
            next_retry_at=utc_now(),
            locked_by="worker-a",
            response_payload_json={
                "ok": False,
                "error_code": 500,
                "description": f"boom {status}",
            },
            request_payload_json={"method": "sendMessage", "chat_id": "@ops", "text": status},
        )
        for status in ("failed", "dead_letter", "blocked")
    ]
    await db_session.commit()
    events = CapturingEvents()
    service = SendService(db_session, _bot_api_client({}), Settings(), events)

    retried = [await service.retry_history(row.id) for row in rows]

    assert [row.status for row in retried] == ["queued", "queued", "queued"]
    assert all(row.error_code is None for row in retried)
    assert all(row.error_message is None for row in retried)
    assert all(row.last_error_kind is None for row in retried)
    assert all(row.retry_after_seconds is None for row in retried)
    assert all(row.next_retry_at is None for row in retried)
    assert all(row.locked_by is None for row in retried)
    assert [row.response_payload_json for row in retried] == [
        {"ok": False, "error_code": 500, "description": "boom failed"},
        {"ok": False, "error_code": 500, "description": "boom dead_letter"},
        {"ok": False, "error_code": 500, "description": "boom blocked"},
    ]
    assert events.events == [
        "send.retry_scheduled",
        "send.retry_scheduled",
        "send.retry_scheduled",
    ]


async def test_deferred_history_row_can_be_cancelled(db_session: AsyncSession) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:token")
    history = SendHistoryRepository(db_session)
    row = await history.create(
        bot_id=bot.id,
        chat_id="@ops",
        media_type="none",
        status="deferred",
        send_mode="queued",
        request_payload_json={"method": "sendMessage", "chat_id": "@ops", "text": "hello"},
    )
    await db_session.commit()
    service = SendService(db_session, _bot_api_client({}), Settings())

    cancelled = await service.cancel_history(row.id)

    assert cancelled.status == "cancelled"


async def test_rate_limiter_defers_before_telegram_call_with_attempt(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:token")
    await db_session.commit()
    seen: dict[str, Any] = {"count": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["count"] += 1
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 77}})

    rate_limiter = SendRateLimiter(
        store=MemoryRateLimitStore(),
        global_limit_per_minute=0,
        bot_limit_per_minute=None,
        chat_limit_per_minute=None,
        destination_limit_per_minute=None,
    )
    service = SendService(
        db_session,
        TelegramBotApiClient(
            "http://telegram-bot-api:8081",
            httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        ),
        Settings(reliability_enabled=True),
        rate_limiter=rate_limiter,
    )
    row = await service.send_text(bot.id, "hello", chat_id="@ops", send_mode="queued")

    processed = await service.process_queued_send(row.id, worker_id="worker-a")
    attempts = await SendAttemptRepository(db_session).list_for_send(row.id)

    assert processed.status == "deferred"
    assert processed.last_error_kind == "rate_limit"
    assert processed.locked_by is None
    assert attempts[0].status == "deferred"
    assert attempts[0].error_kind == "rate_limit"
    assert seen["count"] == 0


async def test_queued_send_event_publish_failure_does_not_break_attempt_integrity(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:token")
    await db_session.commit()
    service = SendService(
        db_session,
        _bot_api_client({}),
        Settings(reliability_enabled=True),
        FailingEvents(),
    )
    row = await service.send_text(bot.id, "hello", chat_id="@ops", send_mode="queued")

    processed = await service.process_queued_send(row.id, worker_id="worker-a")
    attempts = await SendAttemptRepository(db_session).list_for_send(row.id)

    assert processed.status == "succeeded"
    assert processed.locked_by is None
    assert attempts[0].attempt_number == 1
    assert attempts[0].status == "succeeded"


async def test_unexpected_worker_error_is_deferred_with_attempt(
    db_session: AsyncSession,
) -> None:
    token = "1234567890:FAKE_UNIT_TEST_BOT_TOKEN_DO_NOT_USE"

    class ExplodingBotApi:
        async def send_message(self, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError(f"worker failed for {token}")

    bot = await BotRepository(db_session).create(name="ops", token=token)
    await db_session.commit()
    service = SendService(
        db_session,
        ExplodingBotApi(),
        Settings(reliability_enabled=True, send_retry_base_delay_seconds=2),
    )
    row = await service.send_text(bot.id, "hello", chat_id="@ops", send_mode="queued")

    processed = await service.process_queued_send(row.id, worker_id="worker-a")
    attempts = await SendAttemptRepository(db_session).list_for_send(row.id)

    assert processed.status == "deferred"
    assert processed.last_error_kind == "worker_error"
    assert processed.retry_after_seconds == 2
    assert processed.locked_by is None
    assert attempts[0].attempt_number == 1
    assert attempts[0].status == "deferred"
    assert attempts[0].error_kind == "worker_error"
    assert attempts[0].error_message == "worker failed for [REDACTED]"


async def test_cancelled_worker_records_interrupted_attempt_and_keeps_lease(
    db_session: AsyncSession,
) -> None:
    class CancellingBotApi:
        async def send_message(self, **kwargs: Any) -> dict[str, Any]:
            raise asyncio.CancelledError()

    bot = await BotRepository(db_session).create(name="ops", token="123:token")
    await db_session.commit()
    service = SendService(
        db_session,
        CancellingBotApi(),
        Settings(reliability_enabled=True),
    )
    row = await service.send_text(bot.id, "hello", chat_id="@ops", send_mode="queued")

    with pytest.raises(asyncio.CancelledError):
        await service.process_queued_send(row.id, worker_id="worker-a")
    attempts = await SendAttemptRepository(db_session).list_for_send(row.id)

    assert row.status == "sending"
    assert row.locked_by == "worker-a"
    assert attempts[0].attempt_number == 1
    assert attempts[0].status == "interrupted"
    assert attempts[0].error_kind == "worker_cancelled"


async def test_cancelled_locked_event_records_interrupted_attempt(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:token")
    await db_session.commit()
    service = SendService(
        db_session,
        _bot_api_client({}),
        Settings(reliability_enabled=True),
        CancellingLockedEvents(),
    )
    row = await service.send_text(bot.id, "hello", chat_id="@ops", send_mode="queued")

    with pytest.raises(asyncio.CancelledError):
        await service.process_queued_send(row.id, worker_id="worker-a")
    attempts = await SendAttemptRepository(db_session).list_for_send(row.id)

    assert row.status == "sending"
    assert row.locked_by == "worker-a"
    assert attempts[0].attempt_number == 1
    assert attempts[0].status == "interrupted"
    assert attempts[0].error_kind == "worker_cancelled"


async def test_cancelled_after_telegram_success_persists_result_once(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:token")
    await db_session.commit()
    service = SendService(
        db_session,
        _bot_api_client({}),
        Settings(reliability_enabled=True),
    )
    row = await service.send_text(bot.id, "hello", chat_id="@ops", send_mode="queued")
    original_record_attempt = service.queue.record_attempt
    calls = 0

    async def cancelling_record_attempt_once(**kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise asyncio.CancelledError()
        await original_record_attempt(**kwargs)

    service.queue.record_attempt = cancelling_record_attempt_once

    with pytest.raises(asyncio.CancelledError):
        await service.process_queued_send(row.id, worker_id="worker-a")
    attempts = await SendAttemptRepository(db_session).list_for_send(row.id)

    assert row.status == "succeeded"
    assert row.locked_by is None
    assert row.telegram_message_id == 55
    assert calls == 2
    assert len(attempts) == 1
    assert attempts[0].attempt_number == 1
    assert attempts[0].status == "succeeded"


async def test_send_service_publishes_terminal_callback(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:token")
    await db_session.commit()
    callbacks = CapturingCallbacks()
    service = SendService(
        db_session,
        _bot_api_client({}),
        Settings(CALLBACK_ENABLED=True, CALLBACK_URL="http://callbacks.local/send"),
        callback_publisher=callbacks,
    )

    row = await service.send_text(bot.id, "hello", chat_id="@ops")

    assert row.status == "succeeded"
    assert callbacks.payloads == [
        {
            "url": "http://callbacks.local/send",
            "payload": {
                "schema_version": "v1",
                "event_type": "send.succeeded",
                "send_history_id": row.id,
                "status": "succeeded",
            },
        }
    ]
